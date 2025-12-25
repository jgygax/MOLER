const socket = io();
let lightbox = null;
let allJobs = [];
let currentPage = 1;
const itemsPerPage = 8;

document.addEventListener('DOMContentLoaded', () => {
    const pMode = localStorage.getItem('moler_prompt_mode');
    const cPrompt = localStorage.getItem('moler_custom_prompt');
    const aQueue = localStorage.getItem('moler_auto_queue');

    const promptSelect = document.getElementById('promptSelect');
    const customBox = document.getElementById('customPromptBox');
    const autoQueueInput = document.querySelector('input[name="auto_queue"]');

    if (pMode && promptSelect) {
        promptSelect.value = pMode;
        togglePromptInput();
    }
    if (cPrompt && customBox) customBox.value = cPrompt;
    if (aQueue && autoQueueInput) autoQueueInput.checked = (aQueue === 'true');

    // Initial Load
    fetch('/processor/list')
        .then(r => r.json())
        .then(d => {
            allJobs = d;
            renderGallery();
        });
});

// Websocket Listener: Updates instead of full re-render if possible
socket.on('processor_update', (data) => {
    allJobs = data;
    smartUpdateGallery();
});

document.getElementById('camInput').addEventListener('change', function (e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('preview-box').innerHTML = `<img src="${e.target.result}">`;
        };
        reader.readAsDataURL(file);
    }
});

function togglePromptInput() {
    const select = document.getElementById('promptSelect');
    const customBox = document.getElementById('customPromptBox');
    if (select && customBox) {
        customBox.style.display = select.value === 'custom' ? 'block' : 'none';
        localStorage.setItem('moler_prompt_mode', select.value);
    }
}

function resizeImage(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let w = img.width;
                let h = img.height;
                const shortEdge = Math.min(w, h);
                const maxShort = 1024;

                if (shortEdge > maxShort) {
                    const ratio = maxShort / shortEdge;
                    w = Math.round(w * ratio);
                    h = Math.round(h * ratio);
                }

                canvas.width = w;
                canvas.height = h;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, w, h);

                canvas.toBlob((blob) => {
                    resolve(new File([blob], file.name, {
                        type: 'image/jpeg'
                    }));
                }, 'image/jpeg', 0.95);
            };
            img.onerror = reject;
            img.src = e.target.result;
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function savePrefs() {
    const select = document.getElementById('promptSelect');
    const customBox = document.getElementById('customPromptBox');
    const autoQueueInput = document.querySelector('input[name="auto_queue"]');

    if (select) localStorage.setItem('moler_prompt_mode', select.value);
    if (customBox) localStorage.setItem('moler_custom_prompt', customBox.value);
    if (autoQueueInput) localStorage.setItem('moler_auto_queue', autoQueueInput.checked);
}

async function submitForm(e) {
    e.preventDefault();
    savePrefs();

    const btn = e.target.querySelector('button[type="submit"]');
    const originalText = btn.innerText;

    btn.disabled = true;
    btn.innerText = "Processing...";

    const fileInput = document.getElementById('camInput');
    if (!fileInput.files.length) {
        btn.disabled = false;
        btn.innerText = originalText;
        return;
    }

    try {
        const resizedFile = await resizeImage(fileInput.files[0]);
        const formData = new FormData(e.target);
        formData.set('image', resizedFile);

        const res = await fetch('/processor/submit', {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            e.target.reset();
            const pMode = localStorage.getItem('moler_prompt_mode');
            const promptSelect = document.getElementById('promptSelect');
            if (pMode && promptSelect) {
                promptSelect.value = pMode;
                togglePromptInput();
            }
            document.getElementById('preview-box').innerHTML = `
                <i class="fas fa-cloud-upload-alt"></i>
                <span>Select Image</span>
            `;
        } else {
            alert("Upload failed");
        }
    } catch (err) {
        console.error(err);
        alert("Error submitting job");
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

async function startPlot(jobId) {
    try {
        const res = await fetch(`/processor/send_plot/${jobId}`, { method: 'POST' });
        const d = await res.json();
        if (d.status === 'enqueued') {
            alert("Job sent to plotter queue!");
        } else {
            alert("Error: " + (d.error || 'Unknown'));
        }
    } catch (e) {
        alert("Request failed");
    }
}

function changePage(newPage) {
    currentPage = newPage;
    renderGallery(); // Full render on page change
}

function getJobHtml(j) {
    // Determine main thumbnail
    let displayImg;
    const assets = j.assets || [];

    // Prefer static display render, then rmbg, then any png, then original
    if (assets.includes('5_static_render.png')) {
        displayImg = `/processed/${j.id}/5_static_render.png`;
    } else if (assets.includes('1a_rmbg.png')) {
        displayImg = `/processed/${j.id}/1a_rmbg.png`;
    } else if (assets.length > 0) {
        displayImg = `/processed/${j.id}/${assets[0]}`;
    } else {
        displayImg = `/processed/${j.id}/${j.original_file || 'original.jpg'}`;
    }

    if (j.status === 'pending') {
        displayImg += `?opt=${Date.now()}`;
    }

    const isAuto = j.auto_queue && j.queued_automatically ? '<span class="status-badge complete" title="Auto-Queued">AQ</span>' : '';

    // Generate lightbox links for all assets
    let galleryLinks = `<a href="/processed/${j.id}/${j.original_file || 'original.jpg'}" class="glightbox" data-gallery="j-${j.id}" data-title="Original"></a>`;

    assets.forEach(f => {
        if (f.endsWith('.png')) {
            galleryLinks += `<a href="/processed/${j.id}/${f}" class="glightbox" data-gallery="j-${j.id}" data-title="${f}"></a>`;
        }
    });

    return `
        <div class="card-media">
            <a href="${displayImg.split('?')[0]}" class="glightbox" data-gallery="j-${j.id}" data-title="Preview">
                <img src="${displayImg}" loading="lazy">
            </a>
            <div style="display:none;">${galleryLinks}</div>
            ${j.status === 'pending' ? '<div class="status-bar"><i class="fas fa-spinner fa-spin"></i> Processing</div>' : ''}
        </div>
        <div class="card-info">
            <div class="meta">
                <span class="status-badge ${j.status}">${j.status}</span>
                <div style="display:flex; gap:5px;">
                    ${isAuto}
                    <small>${new Date(j.timestamp * 1000).toLocaleTimeString()}</small>
                </div>
            </div>
            <p class="prompt" title="${j.prompt}">${j.prompt || 'No Prompt'}</p>
            ${j.status === 'complete' ?
            `<button class="primary btn-sm" onclick="startPlot('${j.id}')">PLOT <i class="fas fa-paper-plane"></i></button>` : ''}
        </div>
    `;
}

// Smarter update: updates DOM nodes if they exist, to allow Lightbox to potentially stay open
// or at least not flicker aggressively
function smartUpdateGallery() {
    const grid = document.getElementById('gallery-grid');
    if (!grid) return;

    if (allJobs.length === 0) {
        grid.innerHTML = '<div class="empty-msg">No jobs history found. Start by uploading an image.</div>';
        return;
    }

    const { visibleJobs, totalPages } = getPaginationData();
    renderPagination(totalPages);

    // Current Job IDs on screen
    const visibleIds = visibleJobs.map(j => j.id);

    // 1. Remove elements that shouldn't be here (if page changed externally or job deleted)
    Array.from(grid.children).forEach(child => {
        const jid = child.getAttribute('data-job-id');
        if (jid && !visibleIds.includes(jid)) {
            child.remove();
        }
    });

    // 2. Insert or Update
    visibleJobs.forEach((job, index) => {
        let card = document.getElementById(`job-card-${job.id}`);
        const newHtml = getJobHtml(job);

        // Check if just placeholder
        const isEmpty = grid.querySelector('.empty-msg');
        if (isEmpty) isEmpty.remove();

        if (!card) {
            // Create new
            card = document.createElement('div');
            card.className = `gallery-card ${job.status}`;
            card.id = `job-card-${job.id}`;
            card.setAttribute('data-job-id', job.id);
            card.innerHTML = newHtml;

            // Insert at correct position (simple approach: append, since we filtered standard view)
            // Ideally we insert before the next existing element
            const currChildren = Array.from(grid.children);
            if (index < currChildren.length) {
                grid.insertBefore(card, currChildren[index]);
            } else {
                grid.appendChild(card);
            }
        } else {
            // Update existing if content changed (simple string compare for now)
            if (card.innerHTML !== newHtml) {
                card.className = `gallery-card ${job.status}`;
                card.innerHTML = newHtml;
            }
        }
    });

    initLightbox();
}

function getPaginationData() {
    const totalPages = Math.ceil(allJobs.length / itemsPerPage);
    if (currentPage > totalPages) currentPage = totalPages || 1;
    const start = (currentPage - 1) * itemsPerPage;
    const end = start + itemsPerPage;
    return {
        visibleJobs: allJobs.slice(start, end),
        totalPages
    };
}

function renderGallery() {
    // Initial Full Render (used on page change or init)
    const grid = document.getElementById('gallery-grid');
    if (!grid) return;

    if (allJobs.length === 0) {
        grid.innerHTML = '<div class="empty-msg">No jobs history found. Start by uploading an image.</div>';
        document.getElementById('pagination-controls').innerHTML = '';
        return;
    }

    const { visibleJobs, totalPages } = getPaginationData();

    grid.innerHTML = visibleJobs.map(j => `
        <div class="gallery-card ${j.status}" id="job-card-${j.id}" data-job-id="${j.id}">
            ${getJobHtml(j)}
        </div>
    `).join('');

    renderPagination(totalPages);
    initLightbox();
}

function renderPagination(totalPages) {
    const pagination = document.getElementById('pagination-controls');
    if (pagination && totalPages > 1) {
        pagination.innerHTML = `
            <button class="page-btn" onclick="changePage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>
                <i class="fas fa-chevron-left"></i>
            </button>
            <button class="page-btn active">${currentPage}</button>
            <button class="page-btn" onclick="changePage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>
                <i class="fas fa-chevron-right"></i>
            </button>
        `;
    } else if (pagination) {
        pagination.innerHTML = '';
    }
}

function initLightbox() {
    try {
        if (lightbox) {
            lightbox.reload();
        } else {
            lightbox = GLightbox({
                selector: '.glightbox',
                touchNavigation: true,
                loop: true,
                zoomable: true
            });
        }
    } catch (e) {
        console.error("Lightbox init error", e);
    }
}