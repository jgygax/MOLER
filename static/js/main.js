const socket = io();
let plotterState = { x: 0, y: 0, motor_distance: 0, queue_size: 0, is_working: false };
let canvasBounds = { top: 0, left: 0, right: 0, bottom: 0 };

// Connect & Config
socket.on('connect', () => console.log('Connected to MOLER'));

socket.on('config', (bounds) => {
    canvasBounds = bounds;
    console.log('Bounds loaded:', bounds);
});

// Status Stream
socket.on('status_update', (data) => {
    plotterState = data;
    updateVisuals(data);
    updateUI(data);
});

function updateUI(data) {
    const coords = document.getElementById('coords-info');
    const queueInfo = document.getElementById('queue-info');
    const statusText = data.is_working ? 'PLOTTING' : 'IDLE';
    const statusColor = data.is_working ? 'orange' : 'limegreen';

    coords.innerText = `X: ${data.x.toFixed(1)} Y: ${data.y.toFixed(1)}`;
    queueInfo.innerHTML = `Status: <span style="color:${statusColor};font-weight:bold">${statusText}</span> | Queue: ${data.queue_size}`;
}

function updateVisuals(data) {
    const imgMsg = document.getElementById('plotter-feed');
    const canvas = document.getElementById('overlay-canvas');
    if (!canvas || !imgMsg) return;

    // Update camera feed
    if (data.canvas) {
        imgMsg.src = 'data:image/jpeg;base64,' + data.canvas;
    }

    // Ensure logic happens only when image has dimensions
    if (imgMsg.clientWidth === 0) return;

    // Match canvas to image dimensions exactly
    canvas.width = imgMsg.clientWidth;
    canvas.height = imgMsg.clientHeight;
    const ctx = canvas.getContext('2d');

    // Scale: Physical Width (cm) -> Visual Width (px)
    const scale = canvas.width / data.motor_distance;

    const mx_left = 0;
    const my = 0;
    const mx_right = data.motor_distance * scale;

    const px = data.x * scale;
    const py = data.y * scale;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw Bounds
    const b_left = canvasBounds.left * scale;
    const b_top = canvasBounds.top * scale;
    const b_w = (data.motor_distance - canvasBounds.left - canvasBounds.right) * scale;
    const b_h = canvas.height - b_top;

    ctx.strokeStyle = 'rgba(255, 115, 0, 0.2)';
    ctx.lineWidth = 1;
    ctx.strokeRect(b_left, b_top, b_w, b_h);

    // Draw Strings
    ctx.strokeStyle = '#ff7300';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(mx_left, my);
    ctx.lineTo(px, py);
    ctx.moveTo(mx_right, my);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Gondola
    ctx.beginPath();
    ctx.fillStyle = data.z !== 0 ? 'blue' : 'red';
    ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.fill();
}

// Commands
function sendManual(direction) {
    if (plotterState.is_working) return;
    const speed = document.getElementById('speedSlider').value;
    socket.emit('move_manual', { direction, speed });
}

function goHome() {
    if (plotterState.is_working) return;
    socket.emit('set_home');
}

function clearCanvas() {
    socket.emit('clear_canvas');
}

function cancelJob() {
    socket.emit('cancel_job');
}

// File Upload
async function uploadFile() {
    const file = document.getElementById('fileInput').files[0];
    if (!file) return alert('Select a .yaml file');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const d = await res.json();
    } catch (e) { alert(e); }
}

// Joystick Logic
function initJoystick() {
    const box = document.getElementById('joystick');
    const handle = document.getElementById('joystick-handle');
    let resizing = false;
    let bounds, center, radius;

    // Queue Logic variables
    let isBusy = false;
    let pendingCommand = null;

    const calcBounds = () => {
        if (!box) return;
        bounds = box.getBoundingClientRect();
        center = { x: bounds.width / 2, y: bounds.height / 2 };
        radius = bounds.width / 2 - 20;
    };
    calcBounds();
    window.addEventListener('resize', calcBounds);

    const processCommandQueue = (data) => {
        // If plotting is happening, disable joystick logic
        if (plotterState.is_working) return;

        // If system is busy, store the LATEST command (overwrite old) and return
        if (isBusy) {
            pendingCommand = data;
            return;
        }

        isBusy = true;
        socket.emit('move_joystick', data, (ack) => {
            // ACK received from server
            isBusy = false;
            // If a new command arrived while we were busy, send it now
            if (pendingCommand) {
                const next = pendingCommand;
                pendingCommand = null;
                processCommandQueue(next);
            }
        });
    };

    const move = (cx, cy) => {
        let x = cx - bounds.left - center.x;
        let y = cy - bounds.top - center.y;

        const dist = Math.sqrt(x * x + y * y);
        if (dist > radius) {
            x = (x / dist) * radius;
            y = (y / dist) * radius;
        }

        handle.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;

        processCommandQueue({
            x: (x / radius) * 0.5,
            y: (y / radius) * 0.5
        });
    };

    const end = () => {
        resizing = false;
        handle.style.transform = 'translate(-50%, -50%)';
    };

    if (handle) {
        handle.addEventListener('mousedown', () => resizing = true);
        document.addEventListener('mouseup', end);
        document.addEventListener('mousemove', e => resizing && move(e.clientX, e.clientY));

        handle.addEventListener('touchstart', () => resizing = true);
        document.addEventListener('touchend', end);
        document.addEventListener('touchmove', e => {
            if (resizing) {
                e.preventDefault();
                move(e.touches[0].clientX, e.touches[0].clientY);
            }
        });
    }
}

document.addEventListener('DOMContentLoaded', initJoystick);