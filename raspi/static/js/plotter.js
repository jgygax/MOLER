const socket = io();
let plotterState = { x: 0, y: 0, motor_distance: 0, queue: [], is_working: false };
let canvasBounds = { top: 0, left: 0, right: 0, bottom: 0 };
let currentSpeed = 'medium';

// Variable to store the signature of the last rendered queue
let lastQueueState = '';

const SPEEDS = {
    slow: { steps: 50, servo: 0.05, dist: 3 },
    medium: { steps: 300, servo: 0.10, dist: 30 },
    fast: { steps: 1000, servo: 0.50, dist: 100 }
};

socket.on('config', (b) => canvasBounds = b);
socket.on('status_update', (d) => {
    plotterState = d;
    updateVisuals(d);
    updateUI(d);
});

function updateUI(data) {
    const c = document.getElementById('coords-info');
    if (c) c.innerText = `X:${data.x.toFixed(1)} Y:${data.y.toFixed(1)} | ${data.is_working ? 'BUSY' : 'IDLE'}`;

    const list = document.getElementById('job-list-container');
    if (!list) return;

    // Create a unique JSON signature for the current queue state
    const currentQueueState = JSON.stringify({
        working: data.is_working,
        cid: data.current_job_id,
        currentName: data.current_job_name,
        q: data.queue
    });

    // Only overwrite the InnerHTML if the queue data has actually changed.
    // This prevents the DOM buttons from being destroyed while the user is trying to click them.
    if (currentQueueState === lastQueueState) return;
    lastQueueState = currentQueueState;

    let html = '';
    if (data.is_working && data.current_job_id) {
        html += `<div class="job-item current"><span>RUNNING: ${data.current_job_name}</span>
                 <button class="danger btn-sm" onclick="cancelJob('${data.current_job_id}')">X</button></div>`;
    }
    data.queue.forEach(j => {
        html += `<div class="job-item"><span>${j.name}</span>
                 <button class="danger btn-sm" onclick="cancelJob('${j.id}')">X</button></div>`;
    });
    list.innerHTML = html || '<div class="empty-msg">Empty Queue</div>';
}

function updateVisuals(data) {
    const cv = document.getElementById('overlay-canvas');
    const feed = document.getElementById('plotter-feed');
    if (!cv || !feed) return;
    if (data.canvas) feed.src = 'data:image/jpeg;base64,' + data.canvas;

    const rect = feed.getBoundingClientRect();
    cv.width = rect.width;
    cv.height = rect.height;

    if (cv.width === 0 || cv.height === 0) return;

    const ctx = cv.getContext('2d');
    const scale = cv.width / data.motor_distance;

    ctx.clearRect(0, 0, cv.width, cv.height);
    const px = data.x * scale;
    const py = data.y * scale;

    // Draw strings
    ctx.strokeStyle = '#ff7300';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(px, py);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(data.motor_distance * scale, 0);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Draw gondola
    ctx.fillStyle = 'red';
    ctx.beginPath();
    ctx.arc(px, py, 11, 0, Math.PI * 2);
    ctx.fill();
}

function setSpeed(l) {
    currentSpeed = l;
    document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-' + l).classList.add('active');
}

// Fixed syntax errors from original snippet (_ -> *)
function moveXY(dx, dy) { socket.emit('move_xy', { x: dx * SPEEDS[currentSpeed].dist, y: dy * SPEEDS[currentSpeed].dist }); }
function adjustMotor(m, d) { socket.emit('move_raw_motor', { motor: m, steps: SPEEDS[currentSpeed].steps * d }); }
function adjustServo(d) { socket.emit('move_servo_delta', { delta: SPEEDS[currentSpeed].servo * d }); }
function resetHome() { socket.emit('set_home'); }
function clearCanvas() { socket.emit('clear_canvas'); }
function cancelJob(id) { socket.emit('cancel_job', { id: id }); }

async function uploadFile() {
    const f = document.getElementById('fileInput').files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    await fetch('/upload', { method: 'POST', body: fd });
}

document.addEventListener('DOMContentLoaded', () => {
    setSpeed('medium');
    socket.emit('subscribe_plotter');

    // Handle visibility change to save bandwidth
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            socket.emit('unsubscribe_plotter');
        } else {
            socket.emit('subscribe_plotter');
        }
    });
});