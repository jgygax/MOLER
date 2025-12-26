function updateSpeed() {
    const slider = document.getElementById('speedSlider');
    const valueDisplay = document.getElementById('speedValue');
    valueDisplay.textContent = slider.value;
}

function showMessage(elementId, message, isError = false) {
    const msgElement = document.getElementById(elementId);
    msgElement.textContent = message;
    msgElement.className = 'message ' + (isError ? 'error' : 'success');
    msgElement.style.display = 'block';
    setTimeout(() => {
        msgElement.style.display = 'none';
    }, 3000);
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) {
        showMessage('uploadMessage', 'Please select a file', true);
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('uploadMessage', 'File uploaded and parsed successfully!');
        } else {
            showMessage('uploadMessage', data.error || 'Upload failed', true);
        }
    } catch (error) {
        showMessage('uploadMessage', 'Error: ' + error.message, true);
    }
}

async function sendControl(direction) {
    const speed = parseInt(document.getElementById('speedSlider').value);

    try {
        const response = await fetch('/control', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                direction: direction,
                speed: speed
            })
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('controlMessage', `${data.action} with speed ${data.speed}`);
        } else {
            showMessage('controlMessage', data.error || 'Control failed', true);
        }
    } catch (error) {
        showMessage('controlMessage', 'Error: ' + error.message, true);
    }
}

async function moveToPosition(x, y) {
    try {
        const response = await fetch('/move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ x: x, y: y })
        });

        const data = await response.json();

        if (!response.ok) {
            showMessage('controlMessage', data.error || 'Move failed', true);
        }
    } catch (error) {
        showMessage('controlMessage', 'Error: ' + error.message, true);
    }
}

async function setHome() {
    try {
        const response = await fetch('/home', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('controlMessage', 'Home position set!');
        } else {
            showMessage('controlMessage', data.error || 'Home set failed', true);
        }
    } catch (error) {
        showMessage('controlMessage', 'Error: ' + error.message, true);
    }
}

function initJoystick() {
    const joystick = document.getElementById('joystick');
    const handle = document.getElementById('joystick-handle');

    let isDragging = false;
    let centerX = 0;
    let centerY = 0;
    let maxRadius = 0;

    function updateCenter() {
        const rect = joystick.getBoundingClientRect();
        centerX = rect.width / 2;
        centerY = rect.height / 2;
        maxRadius = rect.width / 2 - 30;
    }

    updateCenter();
    window.addEventListener('resize', updateCenter);

    function startDrag(e) {
        isDragging = true;
        e.preventDefault();
    }

    function drag(e) {
        if (!isDragging) return;

        const rect = joystick.getBoundingClientRect();
        const clientX = e.clientX || (e.touches && e.touches[0].clientX);
        const clientY = e.clientY || (e.touches && e.touches[0].clientY);

        let x = clientX - rect.left - centerX;
        let y = clientY - rect.top - centerY;

        const distance = Math.sqrt(x * x + y * y);
        if (distance > maxRadius) {
            x = (x / distance) * maxRadius;
            y = (y / distance) * maxRadius;
        }

        handle.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;

        const normalizedX = x / maxRadius;
        const normalizedY = y / maxRadius;

        const step = 0.5;
        moveToPosition(normalizedX * step, normalizedY * step);
    }

    function endDrag() {
        if (!isDragging) return;
        isDragging = false;
        handle.style.transform = 'translate(-50%, -50%)';
    }

    handle.addEventListener('mousedown', startDrag);
    handle.addEventListener('touchstart', startDrag);

    document.addEventListener('mousemove', drag);
    document.addEventListener('touchmove', drag);

    document.addEventListener('mouseup', endDrag);
    document.addEventListener('touchend', endDrag);
}

async function pollStatus() {
    try {
        const response = await fetch('/status');
        const data = await response.json();

        if (data.active) {
            if (data.canvas) {
                const img = document.getElementById('plotter-canvas');
                img.src = 'data:image/jpeg;base64,' + data.canvas;
            }

            const marker = document.getElementById('head-marker');
            marker.style.display = 'block';

            const pixelsPerCm = 10;
            const x = data.x * pixelsPerCm;
            const y = data.y * pixelsPerCm;

            marker.style.left = x + 'px';
            marker.style.top = y + 'px';

            if (data.z !== 0) {
                marker.style.backgroundColor = 'blue';
            } else {
                marker.style.backgroundColor = 'red';
            }

            drawStrings(data.x, data.y, data.motor_distance);
        }
    } catch (error) {
        console.error("Polling error:", error);
    }
}

function drawStrings(x, y, motorDistance) {
    const canvas = document.getElementById('string-canvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const pixelsPerCm = 10;

    const leftMotorX = 0;
    const leftMotorY = 0;
    const rightMotorX = motorDistance * pixelsPerCm;
    const rightMotorY = 0;
    const gondolaX = x * pixelsPerCm;
    const gondolaY = y * pixelsPerCm;

    ctx.strokeStyle = '#ff7300';
    ctx.lineWidth = 2;

    ctx.beginPath();
    ctx.moveTo(leftMotorX, leftMotorY);
    ctx.lineTo(gondolaX, gondolaY);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(rightMotorX, rightMotorY);
    ctx.lineTo(gondolaX, gondolaY);
    ctx.stroke();

    ctx.fillStyle = '#ff7300';
    ctx.beginPath();
    ctx.arc(leftMotorX, leftMotorY, 5, 0, 2 * Math.PI);
    ctx.fill();

    ctx.beginPath();
    ctx.arc(rightMotorX, rightMotorY, 5, 0, 2 * Math.PI);
    ctx.fill();
}

setInterval(pollStatus, 500);
initJoystick();