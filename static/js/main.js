const socket = io();
let plotterState = { x: 0, y: 0, motor_distance: 0, queue: [], current_job_id: null, is_working: false };
let canvasBounds = { top: 0, left: 0, right: 0, bottom: 0 };
let lastQueueState = ""; // Cache to prevent unnecessary DOM re-creation

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
        coords.innerText = `X: ${data.x.toFixed(1)} Y: ${data.y.toFixed(1)} | ${data.is_working ? 'BUSY' : 'IDLE'}`;
    }

    // Create a signature of the current queue state
    const currentQueueState = JSON.stringify({
        queue: data.queue,
        working: data.is_working,
        curId: data.current_job_id
    });

    // Only re-render the queue HTML if the state has actually changed.
    // This stops the buttons from being destroyed/recreated every 100ms, which was killing the click events.
    if (currentQueueState === lastQueueState) return;
    lastQueueState = currentQueueState;

    const qList = document.getElementById('job-list-container');
    if (!qList) return;

    let html = '';
    // Show current job if exists
    if (data.is_working && data.current_job_id) {
        html += `
            <div class="job-item current">
                <span><i class="fas fa-cog fa-spin"></i> Running</span>
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

    // Gondola
    ctx.beginPath();
    ctx.fillStyle = 'red';
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
    confirm("Clear the drawing?") && socket.emit('clear_canvas');
}

function cancelJob(jobId) {
    socket.emit('cancel_job', { id: jobId });
}

async function uploadFile() {
    const file = document.getElementById('fileInput').files[0];
    if (!file) return alert('Select a .yaml file');
    const formData = new FormData();
    formData.append('file', file);
    try {
        await fetch('/upload', { method: 'POST', body: formData });
    } catch (e) { alert(e); }
}

// Joystick Logic
function initJoystick() {
    const box = document.getElementById('joystick');
    const handle = document.getElementById('joystick-handle');
    let resizing = false, bounds, center, radius;
    let isBusy = false, pendingCommand = null;

    const calcBounds = () => {
        if (!box) return;
        bounds = box.getBoundingClientRect();
        center = { x: bounds.width / 2, y: bounds.height / 2 };
        radius = bounds.width / 2 - 20;
    };
    calcBounds();
    window.addEventListener('resize', calcBounds);

    const processCommandQueue = (data) => {
        if (plotterState.is_working) return;
        if (isBusy) { pendingCommand = data; return; }
        isBusy = true;
        socket.emit('move_joystick', data, () => {
            isBusy = false;
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
        if (dist > radius) { x = (x / dist) * radius; y = (y / dist) * radius; }
        handle.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
        processCommandQueue({ x: (x / radius) * 0.5, y: (y / radius) * 0.5 });
    };

    const end = () => {
        resizing = false;
        handle.style.transform = 'translate(-50%, -50%)';
    };

    if (handle) {
        // Mouse
        handle.addEventListener('mousedown', () => resizing = true);
        document.addEventListener('mouseup', end);
        document.addEventListener('mousemove', e => resizing && move(e.clientX, e.clientY));

        // Touch
        handle.addEventListener('touchstart', (e) => {
            resizing = true;
            e.preventDefault(); // Stop scroll
        });
        document.addEventListener('touchend', end);
        document.addEventListener('touchmove', e => {
            if (resizing) {
                e.preventDefault(); // Stop scroll
                move(e.touches[0].clientX, e.touches[0].clientY);
            }
        }, { passive: false });
    }
}

document.addEventListener('DOMContentLoaded', initJoystick);