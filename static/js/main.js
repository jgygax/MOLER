const socket = io();
let plotterState = { x: 0, y: 0, motor_distance: 0, queue: [], current_job_id: null, current_job_name: null, is_working: false };
let canvasBounds = { top: 0, left: 0, right: 0, bottom: 0 };
let lastQueueState = "";

// Speed Configurations
const SPEEDS = {
    slow: { steps: 50, servo: 0.05, dist: 3, label: 'Slow' },
    medium: { steps: 300, servo: 0.10, dist: 30, label: 'Med' },
    fast: { steps: 1000, servo: 0.50, dist: 100, label: 'Fast' }
};
let currentSpeed = 'medium';

// Connect & Config
socket.on('connect', () => console.log('Connected to MOLER'));

socket.on('config', (bounds) => {
    canvasBounds = bounds;
});

// Status Stream
socket.on('status_update', (data) => {
    plotterState = data;
    updateVisuals(data);
    updateUI(data);
});

function updateUI(data) {
    const coords = document.getElementById('coords-info');
    if (coords) {
        coords.innerText = `X: ${data.x.toFixed(1)} Y: ${data.y.toFixed(1)} W: ${data.w.toFixed(2)} | ${data.is_working ? 'BUSY' : 'IDLE'}`;
    }

    const currentQueueState = JSON.stringify({
        queue: data.queue,
        working: data.is_working,
        curId: data.current_job_id,
        curName: data.current_job_name
    });

    if (currentQueueState === lastQueueState) return;
    lastQueueState = currentQueueState;

    const qList = document.getElementById('job-list-container');
    if (!qList) return;

    let html = '';
    if (data.is_working && data.current_job_id) {
        // Show current job name
        const display = data.current_job_name || 'Processing...';
        html += `
            <div class="job-item current">
                <span><i class="fas fa-cog fa-spin"></i> ${display}</span>
                <button class="danger btn-sm" onclick="cancelJob('${data.current_job_id}')"><i class="fas fa-times"></i></button>
            </div>
        `;
    }

    if (data.queue.length === 0 && !data.is_working) {
        html = '<div style="padding:10px; color:#666; text-align:center">Queue Empty</div>';
    } else {
        data.queue.forEach(job => {
            html += `
                <div class="job-item">
                    <span>${job.name}</span>
                    <button class="danger btn-sm" onclick="cancelJob('${job.id}')"><i class="fas fa-times"></i></button>
                </div>
            `;
        });
    }
    qList.innerHTML = html;
}

function updateVisuals(data) {
    const imgMsg = document.getElementById('plotter-feed');
    const canvas = document.getElementById('overlay-canvas');
    if (!canvas || !imgMsg) return;

    if (data.canvas) imgMsg.src = 'data:image/jpeg;base64,' + data.canvas;
    if (imgMsg.clientWidth === 0) return;

    canvas.width = imgMsg.clientWidth;
    canvas.height = imgMsg.clientHeight;
    const ctx = canvas.getContext('2d');
    const scale = canvas.width / data.motor_distance;

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
    ctx.moveTo(0, 0); ctx.lineTo(px, py);
    ctx.moveTo(data.motor_distance * scale, 0); ctx.lineTo(px, py);
    ctx.stroke();

    // Draw Gondola
    ctx.beginPath();

    // Logic: Red cross if closed (w ~ 0), variable dot if open
    if (data.w <= 0.05) {
        const s = 10; // size of cross
        ctx.strokeStyle = 'red';
        ctx.lineWidth = 3;
        ctx.moveTo(px - s, py - s); ctx.lineTo(px + s, py + s);
        ctx.moveTo(px + s, py - s); ctx.lineTo(px - s, py + s);
        ctx.stroke();
    } else {
        ctx.fillStyle = 'red';
        // Base size 4px, growing up to 20px based on w (0-1)
        const radius = 3 + (data.w * 6);
        ctx.arc(px, py, radius, 0, Math.PI * 2);
        ctx.fill();
    }
}

// --- Interaction Logic ---

function setSpeed(level) {
    currentSpeed = level;
    document.querySelectorAll('.speed-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`btn-${level}`).classList.add('active');
}

function moveXY(dx_mult, dy_mult) {
    const dist = SPEEDS[currentSpeed].dist;
    socket.emit('move_xy', {
        x: dx_mult * dist,
        y: dy_mult * dist
    });
}

function adjustMotor(motor, direction) {
    const steps = SPEEDS[currentSpeed].steps;
    socket.emit('move_raw_motor', {
        motor: motor,
        steps: steps * direction
    });
}

function adjustServo(direction) {
    const delta = SPEEDS[currentSpeed].servo;
    socket.emit('move_servo_delta', {
        delta: delta * direction
    });
}

function resetHome() {
    socket.emit('set_home');
}

function clearCanvas() {
    socket.emit('clear_canvas');
}

function cancelJob(jobId) {
    socket.emit('cancel_job', { id: jobId });
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    if (!file) return alert('Select a .yaml file');

    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        if (!res.ok) {
            alert('Upload failed');
        }
    } catch (e) { alert(e); }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setSpeed('medium');
});
