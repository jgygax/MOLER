# Vibe coded based off https://github.com/sjvasquez/handwriting-synthesis
# to run with newer versions of tensorflow
# Original code by Sean Vasquez

import os
import logging
from collections import defaultdict, namedtuple
import unicodedata
import textwrap


# 1. Config & Legacy Mode Setup
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
os.environ["TF_USE_LEGACY_KERAS"] = "1"

import numpy as np
import tensorflow.compat.v1 as tf

tf.disable_v2_behavior()
import tensorflow_probability as tfp

tfd = tfp.distributions
import svgwrite
from scipy.signal import savgol_filter

# 2. Drawing / Utils Logic
alphabet = [
    "\x00",
    " ",
    "!",
    '"',
    "#",
    "'",
    "(",
    ")",
    ",",
    "-",
    ".",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    ":",
    ";",
    "?",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "Y",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
]
alpha_to_num = defaultdict(int, list(map(reversed, enumerate(alphabet))))


def encode_ascii(ascii_string):
    return np.array(list(map(lambda x: alpha_to_num[x], ascii_string)) + [0])


def align(coords):
    coords = np.copy(coords)
    X, Y = coords[:, 0].reshape(-1, 1), coords[:, 1].reshape(-1, 1)
    X = np.concatenate([np.ones([X.shape[0], 1]), X], axis=1)
    offset, slope = np.linalg.inv(X.T.dot(X)).dot(X.T).dot(Y).squeeze()
    theta = np.arctan(slope)
    rotation_matrix = np.array(
        [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    )
    coords[:, :2] = np.dot(coords[:, :2], rotation_matrix) - offset
    return coords


def denoise(coords):
    coords = np.split(coords, np.where(coords[:, 2] == 1)[0] + 1, axis=0)
    new_coords = []
    for stroke in coords:
        if len(stroke) != 0:
            x_new = savgol_filter(stroke[:, 0], 7, 3, mode="nearest")
            y_new = savgol_filter(stroke[:, 1], 7, 3, mode="nearest")
            xy_coords = np.hstack([x_new.reshape(-1, 1), y_new.reshape(-1, 1)])
            stroke = np.concatenate([xy_coords, stroke[:, 2].reshape(-1, 1)], axis=1)
            new_coords.append(stroke)
    return np.vstack(new_coords)


def offsets_to_coords(offsets):
    return np.concatenate([np.cumsum(offsets[:, :2], axis=0), offsets[:, 2:3]], axis=1)


# 3. TF Utils
def shape(tensor, dim=None):
    if dim is None:
        return tensor.shape.as_list()
    else:
        return tensor.shape.as_list()[dim]


def dense_layer(
    inputs,
    output_units,
    bias=True,
    activation=None,
    batch_norm=None,
    dropout=None,
    scope="dense-layer",
    reuse=False,
):
    with tf.variable_scope(scope, reuse=reuse):
        W = tf.get_variable(
            name="weights",
            initializer=tf.keras.initializers.VarianceScaling(),
            shape=[shape(inputs, -1), output_units],
        )
        z = tf.matmul(inputs, W)
        if bias:
            b = tf.get_variable(
                name="biases",
                initializer=tf.constant_initializer(),
                shape=[output_units],
            )
            z = z + b
        if batch_norm is not None:
            z = tf.layers.batch_normalization(z, training=batch_norm, reuse=reuse)
        z = activation(z) if activation else z
        z = tf.nn.dropout(z, dropout) if dropout is not None else z
        return z


# 4. RNN Ops (Polyfills)
def _like_rnncell(cell):
    return (
        hasattr(cell, "call")
        and hasattr(cell, "state_size")
        and hasattr(cell, "output_size")
    )


def _concat(prefix, suffix, static=False):
    if static:
        return tf.TensorShape(prefix).concatenate(suffix)
    p = tf.reshape(tf.convert_to_tensor(prefix), [-1])
    s = tf.reshape(tf.convert_to_tensor(suffix), [-1])
    return tf.concat((p, s), 0)


def _maybe_tensor_shape_from_tensor(shape):
    if isinstance(shape, tf.Tensor):
        return tf.TensorShape(None)
    return tf.TensorShape(shape)


# Aliases
constant_op = tf
dtypes = tf.dtypes
ops = tf
array_ops = tf
control_flow_ops = tf
math_ops = tf
tensor_array_ops = tf
vs = tf
tensor_shape = tf
nest = tf.nest


def raw_rnn(cell, loop_fn, parallel_iterations=None, swap_memory=False, scope=None):
    if not _like_rnncell(cell):
        raise TypeError("cell must be an instance of RNNCell")
    if not callable(loop_fn):
        raise TypeError("loop_fn must be a callable")
    parallel_iterations = parallel_iterations or 32
    with vs.variable_scope(scope or "rnn") as varscope:
        if not tf.executing_eagerly():
            if varscope.caching_device is None:
                varscope.set_caching_device(lambda op: op.device)
        time = constant_op.constant(0, dtype=dtypes.int32)
        (
            elements_finished,
            next_input,
            initial_state,
            emit_structure,
            init_loop_state,
        ) = loop_fn(time, None, None, None)
        flat_input = nest.flatten(next_input)
        loop_state = (
            init_loop_state
            if init_loop_state is not None
            else constant_op.constant(0, dtype=dtypes.int32)
        )
        input_shape = [input_.get_shape() for input_ in flat_input]
        static_batch_size = input_shape[0][0]
        for input_shape_i in input_shape:
            static_batch_size.merge_with(input_shape_i[0])
        batch_size = static_batch_size.value
        const_batch_size = batch_size
        if batch_size is None:
            batch_size = array_ops.shape(flat_input[0])[0]
        nest.assert_same_structure(initial_state, cell.state_size)
        state = initial_state
        flat_state = nest.flatten(state)
        flat_state = [ops.convert_to_tensor(s) for s in flat_state]
        state = nest.pack_sequence_as(structure=state, flat_sequence=flat_state)
        if emit_structure is not None:
            flat_emit_structure = nest.flatten(emit_structure)
            flat_emit_size = [
                emit.shape if emit.shape.is_fully_defined() else array_ops.shape(emit)
                for emit in flat_emit_structure
            ]
            flat_emit_dtypes = [emit.dtype for emit in flat_emit_structure]
        else:
            emit_structure = cell.output_size
            flat_emit_size = nest.flatten(emit_structure)
            flat_emit_dtypes = [flat_state[0].dtype] * len(flat_emit_size)
        flat_state_size = [
            s.shape if s.shape.is_fully_defined() else array_ops.shape(s)
            for s in flat_state
        ]
        flat_state_dtypes = [s.dtype for s in flat_state]
        flat_emit_ta = [
            tensor_array_ops.TensorArray(
                dtype=dtype_i,
                dynamic_size=True,
                element_shape=(
                    tensor_shape.TensorShape([const_batch_size]).concatenate(
                        _maybe_tensor_shape_from_tensor(size_i)
                    )
                ),
                size=0,
                name="rnn_output_%d" % i,
            )
            for i, (dtype_i, size_i) in enumerate(zip(flat_emit_dtypes, flat_emit_size))
        ]
        emit_ta = nest.pack_sequence_as(
            structure=emit_structure, flat_sequence=flat_emit_ta
        )
        flat_zero_emit = [
            array_ops.zeros(_concat(batch_size, size_i), dtype_i)
            for size_i, dtype_i in zip(flat_emit_size, flat_emit_dtypes)
        ]
        zero_emit = nest.pack_sequence_as(
            structure=emit_structure, flat_sequence=flat_zero_emit
        )
        flat_state_ta = [
            tensor_array_ops.TensorArray(
                dtype=dtype_i,
                dynamic_size=True,
                element_shape=(
                    tensor_shape.TensorShape([const_batch_size]).concatenate(
                        _maybe_tensor_shape_from_tensor(size_i)
                    )
                ),
                size=0,
                name="rnn_state_%d" % i,
            )
            for i, (dtype_i, size_i) in enumerate(
                zip(flat_state_dtypes, flat_state_size)
            )
        ]
        state_ta = nest.pack_sequence_as(structure=state, flat_sequence=flat_state_ta)

        def condition(unused_time, elements_finished, *_):
            return math_ops.logical_not(math_ops.reduce_all(elements_finished))

        def body(
            time, elements_finished, current_input, state_ta, emit_ta, state, loop_state
        ):
            (next_output, cell_state) = cell(current_input, state)
            nest.assert_same_structure(state, cell_state)
            nest.assert_same_structure(cell.output_size, next_output)
            next_time = time + 1
            (next_finished, next_input, next_state, emit_output, next_loop_state) = (
                loop_fn(next_time, next_output, cell_state, loop_state)
            )
            nest.assert_same_structure(state, next_state)
            nest.assert_same_structure(current_input, next_input)
            nest.assert_same_structure(emit_ta, emit_output)
            loop_state = loop_state if next_loop_state is None else next_loop_state

            def _copy_some_through(current, candidate):
                def copy_fn(cur_i, cand_i):
                    if isinstance(cur_i, tensor_array_ops.TensorArray):
                        return cand_i
                    if cur_i.shape.ndims == 0:
                        return cand_i
                    with ops.colocate_with(cand_i):
                        return array_ops.where(elements_finished, cur_i, cand_i)

                return nest.map_structure(copy_fn, current, candidate)

            emit_output = _copy_some_through(zero_emit, emit_output)
            next_state = _copy_some_through(state, next_state)
            emit_ta = nest.map_structure(
                lambda ta, emit: ta.write(time, emit), emit_ta, emit_output
            )
            state_ta = nest.map_structure(
                lambda ta, state: ta.write(time, state), state_ta, next_state
            )
            elements_finished = math_ops.logical_or(elements_finished, next_finished)
            return (
                next_time,
                elements_finished,
                next_input,
                state_ta,
                emit_ta,
                next_state,
                loop_state,
            )

        returned = control_flow_ops.while_loop(
            condition,
            body,
            loop_vars=[
                time,
                elements_finished,
                next_input,
                state_ta,
                emit_ta,
                state,
                loop_state,
            ],
            parallel_iterations=parallel_iterations,
            swap_memory=swap_memory,
        )
        (state_ta, emit_ta, final_state, final_loop_state) = returned[-4:]
        flat_states = nest.flatten(state_ta)
        flat_states = [array_ops.transpose(ta.stack(), (1, 0, 2)) for ta in flat_states]
        states = nest.pack_sequence_as(structure=state_ta, flat_sequence=flat_states)
        flat_outputs = nest.flatten(emit_ta)
        flat_outputs = [
            array_ops.transpose(ta.stack(), (1, 0, 2)) for ta in flat_outputs
        ]
        outputs = nest.pack_sequence_as(structure=emit_ta, flat_sequence=flat_outputs)
        return (states, outputs, final_state)


def rnn_free_run(
    cell,
    initial_state,
    sequence_length,
    initial_input=None,
    scope="dynamic-rnn-free-run",
):
    with vs.variable_scope(scope, reuse=True):
        if initial_input is None:
            initial_input = cell.output_function(initial_state)

    def loop_fn(time, cell_output, cell_state, loop_state):
        next_cell_state = initial_state if cell_output is None else cell_state
        elements_finished = math_ops.logical_or(
            time >= sequence_length, cell.termination_condition(next_cell_state)
        )
        finished = math_ops.reduce_all(elements_finished)
        next_input = control_flow_ops.cond(
            finished,
            lambda: array_ops.zeros_like(initial_input),
            lambda: (
                initial_input
                if cell_output is None
                else cell.output_function(next_cell_state)
            ),
        )
        emit_output = next_input[0] if cell_output is None else next_input
        next_loop_state = None
        return (
            elements_finished,
            next_input,
            next_cell_state,
            emit_output,
            next_loop_state,
        )

    states, outputs, final_state = raw_rnn(cell, loop_fn, scope=scope)
    return states, outputs, final_state


# 5. LSTM Attention Cell
LSTMAttentionCellState = namedtuple(
    "LSTMAttentionCellState",
    ["h1", "c1", "h2", "c2", "h3", "c3", "alpha", "beta", "kappa", "w", "phi"],
)


class LSTMAttentionCell(tf.nn.rnn_cell.RNNCell):
    def __init__(
        self,
        lstm_size,
        num_attn_mixture_components,
        attention_values,
        attention_values_lengths,
        num_output_mixture_components,
        bias,
        reuse=None,
    ):
        self.reuse = reuse
        self.lstm_size = lstm_size
        self.num_attn_mixture_components = num_attn_mixture_components
        self.attention_values = attention_values
        self.attention_values_lengths = attention_values_lengths
        self.window_size = shape(self.attention_values, 2)
        self.char_len = tf.shape(attention_values)[1]
        self.batch_size = tf.shape(attention_values)[0]
        self.num_output_mixture_components = num_output_mixture_components
        self.output_units = 6 * self.num_output_mixture_components + 1
        self.bias = bias

    @property
    def state_size(self):
        return LSTMAttentionCellState(
            self.lstm_size,
            self.lstm_size,
            self.lstm_size,
            self.lstm_size,
            self.lstm_size,
            self.lstm_size,
            self.num_attn_mixture_components,
            self.num_attn_mixture_components,
            self.num_attn_mixture_components,
            self.window_size,
            self.char_len,
        )

    @property
    def output_size(self):
        return self.lstm_size

    def zero_state(self, batch_size, dtype):
        return LSTMAttentionCellState(
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.lstm_size]),
            tf.zeros([batch_size, self.num_attn_mixture_components]),
            tf.zeros([batch_size, self.num_attn_mixture_components]),
            tf.zeros([batch_size, self.num_attn_mixture_components]),
            tf.zeros([batch_size, self.window_size]),
            tf.zeros([batch_size, self.char_len]),
        )

    def __call__(self, inputs, state, scope=None):
        with tf.variable_scope(scope or type(self).__name__, reuse=tf.AUTO_REUSE):
            s1_in = tf.concat([state.w, inputs], axis=1)
            cell1 = tf.nn.rnn_cell.LSTMCell(self.lstm_size)
            s1_out, s1_state = cell1(s1_in, state=(state.c1, state.h1))

            attention_inputs = tf.concat([state.w, inputs, s1_out], axis=1)
            attention_params = dense_layer(
                attention_inputs,
                3 * self.num_attn_mixture_components,
                scope="attention",
            )
            alpha, beta, kappa = tf.split(tf.nn.softplus(attention_params), 3, axis=1)
            kappa = state.kappa + kappa / 25.0
            beta = tf.clip_by_value(beta, 0.01, np.inf)

            kappa_flat, alpha_flat, beta_flat = kappa, alpha, beta
            kappa, alpha, beta = (
                tf.expand_dims(kappa, 2),
                tf.expand_dims(alpha, 2),
                tf.expand_dims(beta, 2),
            )
            enum = tf.reshape(tf.range(self.char_len), (1, 1, self.char_len))
            u = tf.cast(
                tf.tile(enum, (self.batch_size, self.num_attn_mixture_components, 1)),
                tf.float32,
            )
            phi_flat = tf.reduce_sum(
                alpha * tf.exp(-tf.square(kappa - u) / beta), axis=1
            )
            phi = tf.expand_dims(phi_flat, 2)
            sequence_mask = tf.cast(
                tf.sequence_mask(self.attention_values_lengths, maxlen=self.char_len),
                tf.float32,
            )
            sequence_mask = tf.expand_dims(sequence_mask, 2)
            w = tf.reduce_sum(phi * self.attention_values * sequence_mask, axis=1)

            s2_in = tf.concat([inputs, s1_out, w], axis=1)
            cell2 = tf.nn.rnn_cell.LSTMCell(self.lstm_size)
            s2_out, s2_state = cell2(s2_in, state=(state.c2, state.h2))

            s3_in = tf.concat([inputs, s2_out, w], axis=1)
            cell3 = tf.nn.rnn_cell.LSTMCell(self.lstm_size)
            s3_out, s3_state = cell3(s3_in, state=(state.c3, state.h3))

            new_state = LSTMAttentionCellState(
                s1_state.h,
                s1_state.c,
                s2_state.h,
                s2_state.c,
                s3_state.h,
                s3_state.c,
                alpha_flat,
                beta_flat,
                kappa_flat,
                w,
                phi_flat,
            )
            return s3_out, new_state

    def output_function(self, state):
        params = dense_layer(
            state.h3, self.output_units, scope="gmm", reuse=tf.AUTO_REUSE
        )
        pis, mus, sigmas, rhos, es = self._parse_parameters(params)
        mu1, mu2 = tf.split(mus, 2, axis=1)
        mus = tf.stack([mu1, mu2], axis=2)
        sigma1, sigma2 = tf.split(sigmas, 2, axis=1)
        covar_matrix = [
            tf.square(sigma1),
            rhos * sigma1 * sigma2,
            rhos * sigma1 * sigma2,
            tf.square(sigma2),
        ]
        covar_matrix = tf.stack(covar_matrix, axis=2)
        covar_matrix = tf.reshape(
            covar_matrix, (self.batch_size, self.num_output_mixture_components, 2, 2)
        )
        mvn = tfd.MultivariateNormalFullCovariance(
            loc=mus, covariance_matrix=covar_matrix
        )
        b = tfd.Bernoulli(probs=es)
        c = tfd.Categorical(probs=pis)
        sampled_e = b.sample()
        sampled_coords = mvn.sample()
        sampled_idx = c.sample()
        idx = tf.stack([tf.range(self.batch_size), sampled_idx], axis=1)
        coords = tf.gather_nd(sampled_coords, idx)
        return tf.concat([coords, tf.cast(sampled_e, tf.float32)], axis=1)

    def termination_condition(self, state):
        char_idx = tf.cast(tf.argmax(state.phi, axis=1), tf.int32)
        final_char = char_idx >= self.attention_values_lengths - 1
        past_final_char = char_idx >= self.attention_values_lengths
        output = self.output_function(state)
        es = tf.cast(output[:, 2], tf.int32)
        is_eos = tf.equal(es, tf.ones_like(es))
        return tf.logical_or(tf.logical_and(final_char, is_eos), past_final_char)

    def _parse_parameters(self, gmm_params, eps=1e-8, sigma_eps=1e-4):
        pis, sigmas, rhos, mus, es = tf.split(
            gmm_params,
            [
                1 * self.num_output_mixture_components,
                2 * self.num_output_mixture_components,
                1 * self.num_output_mixture_components,
                2 * self.num_output_mixture_components,
                1,
            ],
            axis=-1,
        )
        pis = pis * (1 + tf.expand_dims(self.bias, 1))
        sigmas = sigmas - tf.expand_dims(self.bias, 1)
        pis = tf.nn.softmax(pis, axis=-1)
        pis = tf.where(pis < 0.01, tf.zeros_like(pis), pis)
        sigmas = tf.clip_by_value(tf.exp(sigmas), sigma_eps, np.inf)
        rhos = tf.clip_by_value(tf.tanh(rhos), eps - 1.0, 1.0 - eps)
        es = tf.clip_by_value(tf.nn.sigmoid(es), eps, 1.0 - eps)
        es = tf.where(es < 0.01, tf.zeros_like(es), es)
        return pis, mus, sigmas, rhos, es


# 6. Generator
class HandwritingGenerator(object):
    def __init__(
        self,
        checkpoint_dir="/app/handwriting/checkpoints",
        lstm_size=400,
        output_mixture_components=20,
        attention_mixture_components=10,
    ):
        self.lstm_size = lstm_size
        self.output_mixture_components = output_mixture_components
        self.attention_mixture_components = attention_mixture_components
        self.output_units = self.output_mixture_components * 6 + 1
        self.graph = tf.Graph()
        with self.graph.as_default():
            with tf.device("/cpu:0"):
                self.build_graph()
                self.saver = tf.train.Saver(max_to_keep=1)
                self.session = tf.Session(graph=self.graph)
                ckpt = tf.train.latest_checkpoint(checkpoint_dir)
                if ckpt:
                    self.saver.restore(self.session, ckpt)
                    print(f"Restored from {ckpt}")
                else:
                    raise Exception("No checkpoint found.")

    def build_graph(self):
        self.sample_tsteps = tf.placeholder(tf.int32, [])
        self.num_samples = tf.placeholder(tf.int32, [])
        self.c = tf.placeholder(tf.int32, [None, None])
        self.c_len = tf.placeholder(tf.int32, [None])
        self.bias = tf.placeholder_with_default(
            tf.zeros([self.num_samples], dtype=tf.float32), [None]
        )
        self.prime = tf.placeholder_with_default(False, [])
        self.x_prime = tf.placeholder(tf.float32, [None, None, 3])
        self.x_prime_len = tf.placeholder(tf.int32, [None])

        cell = LSTMAttentionCell(
            lstm_size=self.lstm_size,
            num_attn_mixture_components=self.attention_mixture_components,
            attention_values=tf.one_hot(self.c, len(alphabet)),
            attention_values_lengths=self.c_len,
            num_output_mixture_components=self.output_mixture_components,
            bias=self.bias,
        )

        def sample():
            initial_state = cell.zero_state(self.num_samples, dtype=tf.float32)
            initial_input = tf.concat(
                [
                    tf.zeros([self.num_samples, 2]),
                    tf.ones([self.num_samples, 1]),
                ],
                axis=1,
            )
            return rnn_free_run(
                cell=cell,
                sequence_length=self.sample_tsteps,
                initial_state=initial_state,
                initial_input=initial_input,
                scope="rnn",
            )[1]

        def primed_sample():
            initial_state = cell.zero_state(self.num_samples, dtype=tf.float32)
            primed_state = tf.nn.dynamic_rnn(
                cell=cell,
                inputs=self.x_prime,
                sequence_length=self.x_prime_len,
                dtype=tf.float32,
                initial_state=initial_state,
                scope="rnn",
            )[1]
            return rnn_free_run(
                cell=cell,
                sequence_length=self.sample_tsteps,
                initial_state=primed_state,
                scope="rnn",
            )[1]

        self.sampled_sequence = tf.cond(self.prime, primed_sample, sample)

    def generate(
        self, text, filename, bias=1.0, style=None, width=75, align_mode="center"
    ):
        # Remove umlauts and prep text
        text = (
            unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore")
            .decode("ascii")
        )

        # Handle manual newlines first, then wrap
        raw_lines = text.split("\n")
        lines = []
        for raw_line in raw_lines:
            if not raw_line:
                lines.append("")
                continue
            wrapped = textwrap.wrap(raw_line, width=width)
            if not wrapped:
                lines.append("")
            else:
                lines.extend(wrapped)

        if not lines:
            lines = [" "]

        all_strokes = []
        for line in lines:
            if not line:
                all_strokes.append(None)
                continue

            encoded = encode_ascii(line)
            
            # Prepare feed dict
            feed = {
                self.num_samples: 1,
                self.sample_tsteps: 40 * len(line),
                self.bias: [bias],
                self.prime: style is not None,
            }

            if style is not None:
                style_path = os.path.join(
                    os.path.dirname(__file__), f"/app/handwriting/styles/style-{style}-strokes.npy"
                )
                char_path = os.path.join(
                    os.path.dirname(__file__), f"/app/handwriting/styles/style-{style}-chars.npy"
                )
                x_p = np.load(style_path)
                c_p_str = (
                    np.load(char_path).tostring().decode("utf-8")
                )
                
                # Prepend priming text
                full_text = c_p_str + " " + line
                encoded_full = encode_ascii(full_text)
                
                chars = np.zeros([1, len(encoded_full)])
                chars[0, :] = encoded_full
                chars_len = [len(encoded_full)]
                
                x_prime_in = np.zeros([1, len(x_p), 3])
                x_prime_in[0, :, :] = x_p
                x_prime_len_in = [len(x_p)]

                feed.update({
                    self.c: chars,
                    self.c_len: chars_len,
                    self.x_prime: x_prime_in,
                    self.x_prime_len: x_prime_len_in,
                })
            else:
                chars = np.zeros([1, len(encoded)])
                chars[0, :] = encoded
                chars_len = [len(encoded)]
                
                # Dummy priming data for placeholders (required even if unused by cond branch in some TF versions)
                feed.update({
                    self.c: chars,
                    self.c_len: chars_len,
                    self.x_prime: np.zeros([1, 1, 3]),
                    self.x_prime_len: [0],
                })

            [samples] = self.session.run([self.sampled_sequence], feed_dict=feed)
            all_strokes.append(samples[0])

        # Drawing logic
        line_height = 60
        padding = 20  # Padding around the content

        # First pass: determine actual content bounds
        all_processed_strokes = []
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        initial_coord = np.array([0, -(3 * line_height / 4)])

        for strokes in all_strokes:
            if strokes is None:  # Empty line
                initial_coord[1] -= line_height
                all_processed_strokes.append(None)
                continue

            offsets = strokes.copy()
            offsets[:, :2] *= 1.5
            strokes = offsets_to_coords(offsets)
            strokes = denoise(strokes)
            strokes[:, :2] = align(strokes[:, :2])
            strokes[:, 1] *= -1

            # Reset to 0 relative to min
            strokes[:, :2] -= strokes[:, :2].min()
            
            # Apply initial coord (vertical move)
            strokes[:, :2] += initial_coord
            
            all_processed_strokes.append(strokes)
            
            # Track bounds
            min_x = min(min_x, strokes[:, 0].min())
            max_x = max(max_x, strokes[:, 0].max())
            min_y = min(min_y, strokes[:, 1].min())
            max_y = max(max_y, strokes[:, 1].max())
            
            initial_coord[1] += line_height

        # Calculate tight dimensions
        content_width = max_x - min_x
        content_height = max_y - min_y
        view_width = content_width + 2 * padding
        view_height = content_height + 2 * padding

        # Create SVG with pixel dimensions
        dwg = svgwrite.Drawing(filename=filename, size=(f"{view_width}", f"{view_height}"))
        dwg.viewbox(width=view_width, height=view_height)

        # Second pass: draw with adjusted coordinates
        for strokes in all_processed_strokes:
            if strokes is None:
                continue
            
            # Adjust coordinates to account for padding and min bounds
            strokes[:, 0] = strokes[:, 0] - min_x + padding
            strokes[:, 1] = strokes[:, 1] - min_y + padding
            
            # Apply horizontal alignment if desired
            if align_mode == "center":
                x_offset = (view_width - content_width) / 2 - padding
                strokes[:, 0] += x_offset
            elif align_mode == "right":
                x_offset = view_width - content_width - padding
                strokes[:, 0] += x_offset
            
            prev_eos = 1.0
            p = "M{},{} ".format(0, 0)
            for x, y, eos in zip(*strokes.T):
                p += "{}{},{} ".format("M" if prev_eos == 1.0 else "L", x, y)
                prev_eos = eos
            path = svgwrite.path.Path(p)
            path = path.stroke(color="black", width=2, linecap="round").fill("none")
            dwg.add(path)

        dwg.save()
if __name__ == "__main__":
    model = HandwritingGenerator(
        os.path.join(os.path.dirname(__file__), "../checkpoints")
    )
    long_text = (
        "This is a text with\nmanual newlines\n"
        "and vary long lines that should automatically wrap because they exceed the width limit."
    )
    
    # Test Left Align
    model.generate(long_text, "hello_left.svg", width=50, align_mode="left", style=1)
    
    # Test Center Align
    model.generate(long_text, "hello_center.svg", width=50, align_mode="center", style=5)
    
    # Test Right Align
    model.generate(long_text, "hello_right.svg", width=50, align_mode="right", style=8)
    
    print("Generated hello_left.svg, hello_center.svg, hello_right.svg")
