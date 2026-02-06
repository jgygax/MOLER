/**
 * HUID - Head-Up Interface Display
 * Mouse-only control system for VR goggle use
 */

(function() {
    'use strict';

    const state = {
        currentMode: 'camera',
        activeControl: null,
        hoveredElement: null,
        isLocked: false,
        lockSequence: [],
        targetSequence: ['L', 'R', 'R', 'L', 'R', 'L', 'L'],
        cameras: [],
        currentCameraIndex: 0,
        zoomLevel: 1.0,
        minZoom: 0.1,
        maxZoom: 10.0,
        panX: 0,
        panY: 0,
        zoomStep: 0.05,
        panStep: 30,
        frames: [],
        totalFrameCount: 0,
        currentFrameTimestamp: null,
        processedImages: [],
        currentProcessedIndex: 0,
        currentWorkflowIndex: 0,
        workflows: ['clean', 'realistic', 'kawaii', 'full'],
        autoGallery: false,
        isFullscreen: false,
        settings: { yStart: 10, yEnd: 90 },
        db: null,
        stream: null,
        lastStoreTime: 0,
        frameId: 0,
        statusInterval: null,
        workflowCache: new Map(),
        loadingImages: new Set() // Track which images are currently loading
    };

    const elements = {};
    const DB_NAME = 'HUIDStorage';
    const DB_VERSION = 3;
    const MAX_DB_FRAMES = 1000;
    const FETCH_TIMEOUT = 15000;

    const OPTION_CONTROLS = ['scroll-workflows', 'switch-camera', 'zoom', 'pan-x', 'pan-y', 'y-start', 'y-end', 'auto-gallery'];
    const ACTION_CONTROLS = ['process', 'send-plotter', 'fullscreen', 'scroll-timeline', 'scroll-images'];

    document.addEventListener('DOMContentLoaded', init);

    async function init() {
        cacheElements();
        loadSettings();
        applyYConstraints();
        await initDatabase();
        await updateTotalFrameCount();
        await enumerateCameras();
        await startCamera();
        setupEventListeners();
        startFrameCapture();
        updateUI();
    }

    function cacheElements() {
        elements.video = document.getElementById('camera-video');
        elements.canvas = document.getElementById('capture-canvas');
        elements.wrapper = document.getElementById('huid-wrapper');
        elements.uiContainer = document.getElementById('ui-container');
        elements.topBar = document.getElementById('top-bar');
        elements.bottomBar = document.getElementById('bottom-bar');
        elements.overlay = document.getElementById('overlay-image');
        elements.status = document.getElementById('status-text');
        elements.timelineBar = document.getElementById('timeline-bar');
        elements.timelineProgress = document.getElementById('timeline-progress');
        
        elements.modes = {
            camera: document.getElementById('mode-camera'),
            timeline: document.getElementById('mode-timeline'),
            gallery: document.getElementById('mode-gallery'),
            settings: document.getElementById('mode-settings'),
            lock: document.getElementById('mode-lock')
        };
    }

    async function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUT) {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeout);
        
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            clearTimeout(id);
            return response;
        } catch (error) {
            clearTimeout(id);
            if (error.name === 'AbortError') throw new Error('Request timeout');
            throw error;
        }
    }

    function initDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => { state.db = request.result; resolve(); };
            request.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (db.objectStoreNames.contains('frames')) db.deleteObjectStore('frames');
                const store = db.createObjectStore('frames', { keyPath: 'id', autoIncrement: true });
                store.createIndex('timestamp', 'timestamp', { unique: false });
            };
        });
    }

    async function updateTotalFrameCount() {
        if (!state.db) return;
        return new Promise((resolve) => {
            const tx = state.db.transaction(['frames'], 'readonly');
            const store = tx.objectStore('frames');
            const request = store.count();
            request.onsuccess = () => {
                state.totalFrameCount = Math.max(request.result, state.frames.length);
                resolve();
            };
            request.onerror = () => resolve();
        });
    }

    function loadSettings() {
        const saved = localStorage.getItem('huid_settings');
        if (saved) {
            const parsed = JSON.parse(saved);
            state.settings = { ...state.settings, ...parsed.settings };
            state.currentCameraIndex = parsed.currentCameraIndex || 0;
            state.autoGallery = parsed.autoGallery || false;
            state.currentWorkflowIndex = parsed.currentWorkflowIndex || 0;
        }
    }

    function saveSettings() {
        const toSave = {
            settings: state.settings,
            currentCameraIndex: state.currentCameraIndex,
            autoGallery: state.autoGallery,
            currentWorkflowIndex: state.currentWorkflowIndex
        };
        localStorage.setItem('huid_settings', JSON.stringify(toSave));
    }

    function applyYConstraints() {
        document.documentElement.style.setProperty('--y-start', state.settings.yStart + '%');
        document.documentElement.style.setProperty('--y-end', state.settings.yEnd + '%');
    }

    async function enumerateCameras() {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            state.cameras = devices.filter(d => d.kind === 'videoinput');
        } catch (e) { console.error('Camera enumeration error:', e); }
    }

    function getCurrentCameraName() {
        const cam = state.cameras[state.currentCameraIndex];
        if (!cam) return 'Camera';
        let name = cam.label || `Cam ${state.currentCameraIndex + 1}`;
        name = name.replace(/camera|webcam|integrated/i, '').trim();
        if (!name) name = `Cam ${state.currentCameraIndex + 1}`;
        if (name.length > 12) name = name.substring(0, 10) + '..';
        return name;
    }

    async function startCamera() {
        if (state.stream) state.stream.getTracks().forEach(t => t.stop());
        try {
            const constraints = { video: { width: { ideal: 512 }, height: { ideal: 512 } } };
            if (state.cameras[state.currentCameraIndex]?.deviceId) {
                constraints.video.deviceId = { exact: state.cameras[state.currentCameraIndex].deviceId };
            }
            state.stream = await navigator.mediaDevices.getUserMedia(constraints);
            elements.video.srcObject = state.stream;
        } catch (e) { console.error('Camera error:', e); }
    }

    function switchCamera() {
        if (state.cameras.length <= 1) return;
        state.currentCameraIndex = (state.currentCameraIndex + 1) % state.cameras.length;
        saveSettings();
        startCamera();
        updateUI();
    }

    function startFrameCapture() {
        const ctx = elements.canvas.getContext('2d');
        
        setInterval(() => {
            if (!elements.video.videoWidth) return;
            elements.canvas.width = 512;
            elements.canvas.height = 512;
            ctx.drawImage(elements.video, 0, 0, 512, 512);
            const dataUrl = elements.canvas.toDataURL('image/jpeg', 0.7);
            const now = Date.now();
            
            const frame = { id: ++state.frameId, timestamp: now, dataUrl };
            state.frames.unshift(frame);
            
            if (state.frames.length > 300) state.frames.pop();
            
            if (now - state.lastStoreTime >= 100) {
                storeFrame(frame);
                state.lastStoreTime = now;
                updateTotalFrameCount();
            }
            
            // Update timeline display with throttling and mode check
            if (state.currentMode === 'timeline') {
                // Only update every 100ms to reduce jitter
                if (!state.lastTimelineUpdate || now - state.lastTimelineUpdate >= 100) {
                    updateTimelineDisplay();
                    state.lastTimelineUpdate = now;
                }
            }
        }, 33);
    }

    function storeFrame(frame) {
        if (!state.db) return;
        try {
            const tx = state.db.transaction(['frames'], 'readwrite');
            const store = tx.objectStore('frames');
            store.add({ timestamp: frame.timestamp, dataUrl: frame.dataUrl }).onsuccess = () => thinOutFramesIfNeeded();
        } catch (e) { console.error('Store error:', e); }
    }

    function thinOutFramesIfNeeded() {
        if (!state.db) return;
        const tx = state.db.transaction(['frames'], 'readonly');
        const store = tx.objectStore('frames');
        store.count().onsuccess = (e) => {
            if (e.target.result > MAX_DB_FRAMES) {
                const deleteTx = state.db.transaction(['frames'], 'readwrite');
                const deleteStore = deleteTx.objectStore('frames');
                const index = deleteStore.index('timestamp');
                const cursorRequest = index.openCursor(null, 'prev');
                let position = 0;
                cursorRequest.onsuccess = (e) => {
                    const cursor = e.target.result;
                    if (cursor) {
                        if (position >= 100 && position % 2 === 1) cursor.delete();
                        position++;
                        cursor.continue();
                    }
                };
            }
        };
    }

    async function loadFramesFromDB(offset = 0, limit = 100) {
        if (!state.db) return [];
        return new Promise((resolve, reject) => {
            const tx = state.db.transaction(['frames'], 'readonly');
            const store = tx.objectStore('frames');
            const index = store.index('timestamp');
            const frames = [];
            const request = index.openCursor(null, 'prev');
            let skipped = 0, collected = 0;
            
            request.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor && collected < limit) {
                    if (skipped < offset) {
                        skipped++;
                        cursor.continue();
                    } else {
                        frames.push({ id: cursor.value.id, timestamp: cursor.value.timestamp, dataUrl: cursor.value.dataUrl });
                        collected++;
                        cursor.continue();
                    }
                } else resolve(frames);
            };
            request.onerror = () => reject(request.error);
        });
    }

    function setupEventListeners() {
        document.addEventListener('touchstart', e => e.preventDefault(), { passive: false });
        document.addEventListener('touchmove', e => e.preventDefault(), { passive: false });
        document.addEventListener('wheel', handleWheel, { passive: false });
        document.addEventListener('mousedown', handleMouseDown);
        document.addEventListener('contextmenu', e => e.preventDefault());
        document.addEventListener('fullscreenchange', () => { state.isFullscreen = !!document.fullscreenElement; updateUI(); });
    }

    function toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(e => console.error('Fullscreen error:', e));
        } else document.exitFullscreen();
    }

    function handleWheel(e) {
        e.preventDefault();
        if (state.isLocked) return;
        const delta = e.deltaY > 0 ? 1 : -1;
        if (state.activeControl) performActiveAction(delta);
        else navigateElements(delta);
    }

    function navigateElements(delta) {
        const els = getNavigableElements();
        const currentIdx = els.indexOf(state.hoveredElement);
        let newIdx = currentIdx + delta;
        if (newIdx < 0) newIdx = els.length - 1;
        if (newIdx >= els.length) newIdx = 0;
        state.hoveredElement = els[newIdx];
        updateUI();
    }

    function getNavigableElements() {
        if (state.isLocked) return [];
        return ['camera', 'timeline', 'gallery', 'settings', 'lock', ...getCurrentControls()];
    }

    function getCurrentControls() {
        if (state.isLocked) return [];
        switch (state.currentMode) {
            case 'camera': return ['zoom', 'pan-x', 'pan-y', 'switch-camera'];
            case 'timeline': return ['scroll-timeline', 'process', 'auto-gallery'];
            case 'gallery': return ['scroll-images', 'scroll-workflows', 'send-plotter'];
            case 'settings': return ['y-start', 'y-end', 'fullscreen'];
            default: return [];
        }
    }

    function handleMouseDown(e) {
        e.preventDefault();
        if (state.isLocked) { checkLockSequence(e.button === 0 ? 'L' : 'R'); return; }
        if (e.button === 0) handleLeftClick();
        else if (e.button === 2) handleRightClick();
    }

    function formatTimeAgo(timestamp) {
        const seconds = Math.floor((Date.now() - timestamp) / 1000);
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) {
            const m = Math.floor(seconds / 60), s = seconds % 60;
            return s > 0 ? `${m}m ${s}s ago` : `${m}m ago`;
        }
        const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
        return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
    }

    function getFrameAgeColor(timestamp) {
        const ageMs = Date.now() - timestamp, maxAge = 3600000;
        if (ageMs < 10000) {
            const t = ageMs / 10000, r = Math.round(0 + t * 170), g = 255, b = 0;
            return `rgb(${r}, ${g}, ${b})`;
        } else if (ageMs < 60000) {
            const t = (ageMs - 10000) / 50000, r = 170 + Math.round(t * 85), g = 255 - Math.round(t * 85), b = 0;
            return `rgb(${r}, ${g}, ${b})`;
        } else if (ageMs < maxAge) {
            const t = (ageMs - 60000) / (maxAge - 60000);
            if (t < 0.5) {
                const localT = t * 2, r = 255, g = 170 - Math.round(localT * 170), b = 0;
                return `rgb(${r}, ${g}, ${b})`;
            } else {
                const localT = (t - 0.5) * 2, r = 255 - Math.round(localT * 85), g = 0, b = Math.round(localT * 255);
                return `rgb(${r}, ${g}, ${b})`;
            }
        }
        return '#aa00ff';
    }

    function startStatusUpdates() {
        if (state.statusInterval) clearInterval(state.statusInterval);
        state.statusInterval = setInterval(() => {
            if (state.currentMode === 'timeline' && state.currentFrameTimestamp) {
                updateStatus(formatTimeAgo(state.currentFrameTimestamp));
                const frame = state.frames.find(f => f.timestamp === state.currentFrameTimestamp);
                if (frame && elements.timelineProgress) {
                    elements.timelineProgress.style.backgroundColor = getFrameAgeColor(frame.timestamp);
                }
            }
        }, 1000);
    }

    function stopStatusUpdates() {
        if (state.statusInterval) {
            clearInterval(state.statusInterval);
            state.statusInterval = null;
        }
    }

    function getLockStatusText() {
        const entered = state.lockSequence.join('');
        const remaining = state.targetSequence.slice(state.lockSequence.length).join('');
        return `${entered}[${remaining}]`;
    }

    function checkLockSequence(input) {
        const expected = state.targetSequence[state.lockSequence.length];
        if (input !== expected) {
            state.lockSequence = [];
            updateStatus(getLockStatusText());
            return;
        }
        state.lockSequence.push(input);
        if (state.lockSequence.length === state.targetSequence.length) {
            state.isLocked = false;
            state.lockSequence = [];
            state.currentMode = 'camera';
            state.hoveredElement = 'camera';
            elements.wrapper.classList.remove('locked');
            updateStatus('Unlocked!');
            updateUI();
        } else updateStatus(getLockStatusText());
    }

    function handleLeftClick() {
        const el = state.hoveredElement;
        if (!el) return;
        
        if (['camera', 'timeline', 'gallery', 'settings', 'lock'].includes(el)) {
            if (state.activeControl) state.activeControl = null;
            
            if (el === 'lock') {
                state.isLocked = true;
                state.currentMode = 'lock';
                state.lockSequence = [];
                elements.wrapper.classList.add('locked');
                updateStatus(getLockStatusText());
                stopStatusUpdates();
                updateUI();
                return;
            }
            
            if ((state.currentMode === 'gallery' || state.currentMode === 'timeline') && el !== state.currentMode) {
                hideOverlay();
            }
            
            state.currentMode = el;
            const controls = getCurrentControls();
            if (controls.length > 0) {
                state.hoveredElement = controls[0];
                if (el === 'timeline' && controls[0] === 'scroll-timeline') {
                    state.activeControl = 'scroll-timeline';
                    showTimeline();
                } else if (el === 'gallery' && controls[0] === 'scroll-images') {
                    state.activeControl = 'scroll-images';
                    showGallery();
                }
            } else state.hoveredElement = el;
            
            if (el === 'timeline' && state.activeControl !== 'scroll-timeline') showTimeline();
            else if (el === 'gallery' && state.activeControl !== 'scroll-images') showGallery();
            else if (el === 'camera') {
                hideOverlay();
                stopStatusUpdates();
            }
            
            updateUI();
            return;
        }
        
        if (state.activeControl === el) state.activeControl = null;
        else {
            state.activeControl = el;
            if (el === 'process') processFrame();
            if (el === 'send-plotter') sendToPlotter();
            if (el === 'switch-camera') switchCamera();
            if (el === 'auto-gallery') { 
                state.autoGallery = !state.autoGallery; 
                saveSettings();
                state.activeControl = null; 
            }
            if (el === 'fullscreen') toggleFullscreen();
        }
        updateUI();
    }

    function handleRightClick() {
        if (state.activeControl) { state.activeControl = null; updateUI(); }
    }

    function performActiveAction(delta) {
        const scrollMultiplier = (state.activeControl === 'scroll-timeline') ? 5 : 1;
        const effectiveDelta = delta * scrollMultiplier;
        
        switch (state.activeControl) {
            case 'zoom':
                state.zoomLevel += delta * state.zoomStep;
                state.zoomLevel = Math.max(state.minZoom, Math.min(state.maxZoom, state.zoomLevel));
                updateCameraTransform();
                updateStatus(`Zoom: ${state.zoomLevel.toFixed(1)}x`);
                break;
            case 'pan-x': 
                state.panX += delta * state.panStep; 
                updateCameraTransform(); 
                updateStatus(`Pan X: ${state.panX}px`);
                break;
            case 'pan-y': 
                state.panY += delta * state.panStep; 
                updateCameraTransform(); 
                updateStatus(`Pan Y: ${state.panY}px`);
                break;
            case 'scroll-timeline': scrollTimeline(effectiveDelta); break;
            case 'scroll-images': scrollGallery(delta); break;
            case 'scroll-workflows': 
                scrollWorkflows(delta); 
                saveSettings();
                break;
            case 'y-start':
                state.settings.yStart = Math.max(0, Math.min(80, state.settings.yStart + delta));
                saveSettings(); 
                applyYConstraints(); 
                break;
            case 'y-end':
                state.settings.yEnd = Math.max(20, Math.min(100, state.settings.yEnd + delta));
                saveSettings(); 
                applyYConstraints(); 
                break;
        }
        updateUI();
    }

    function updateCameraTransform() {
        elements.video.style.transform = `translate(calc(-50% + ${-state.panX}px), calc(-50% + ${-state.panY}px)) scale(${state.zoomLevel})`;
    }

    function getCurrentFrameIndex() {
        if (!state.currentFrameTimestamp) return 0;
        if (state.frames.length === 0) return 0;
        
        // Find by exact timestamp match first
        const exactIdx = state.frames.findIndex(f => f.timestamp === state.currentFrameTimestamp);
        if (exactIdx >= 0) return exactIdx;
        
        // If exact match not found (frame may have been thinned out), find closest
        let closestIdx = 0;
        let minDiff = Infinity;
        
        for (let i = 0; i < state.frames.length; i++) {
            const diff = Math.abs(state.frames[i].timestamp - state.currentFrameTimestamp);
            if (diff < minDiff) {
                minDiff = diff;
                closestIdx = i;
            }
        }
        
        // Update the timestamp to match what we found
        state.currentFrameTimestamp = state.frames[closestIdx].timestamp;
        return closestIdx;
    }

    function updateTimelineDisplay() {
        if (!elements.timelineProgress) return;
        if (state.totalFrameCount === 0 || state.frames.length === 0) {
            elements.timelineProgress.style.width = '0%';
            return;
        }
        
        const currentIdx = getCurrentFrameIndex();
        // Use the larger of total count or frames length for calculation
        const totalCount = Math.max(state.totalFrameCount, state.frames.length);
        const progress = totalCount > 1 ? (currentIdx / (totalCount - 1)) * 100 : 0;
        elements.timelineProgress.style.width = `${Math.min(progress, 100)}%`;
        
        const frame = state.frames[currentIdx];
        if (frame) {
            elements.timelineProgress.style.backgroundColor = getFrameAgeColor(frame.timestamp);
        }
    }

    async function showTimeline() {
        if (state.frames.length === 0) {
            const dbFrames = await loadFramesFromDB(0, 100);
            state.frames = dbFrames;
        }
        
        if (state.frames.length > 0) {
            state.currentFrameTimestamp = state.frames[0].timestamp;
            const frame = state.frames[0];
            elements.overlay.src = frame.dataUrl;
            elements.overlay.style.display = 'block';
            elements.overlay.style.filter = 'none';
            if (elements.timelineBar) elements.timelineBar.classList.add('visible');
            updateTimelineDisplay();
            updateStatus(formatTimeAgo(frame.timestamp));
            startStatusUpdates();
        }
    }

    async function scrollTimeline(delta) {
        if (state.frames.length === 0) return;
        const currentIdx = getCurrentFrameIndex();
        const newIndex = currentIdx + delta;
        
        if (newIndex >= state.frames.length - 10) {
            const moreFrames = await loadFramesFromDB(state.frames.length, 50);
            if (moreFrames.length > 0) state.frames = state.frames.concat(moreFrames);
        }
        
        const clampedIndex = Math.max(0, Math.min(state.frames.length - 1, newIndex));
        const frame = state.frames[clampedIndex];
        state.currentFrameTimestamp = frame.timestamp;
        elements.overlay.src = frame.dataUrl;
        elements.overlay.style.filter = 'none';
        updateTimelineDisplay();
        updateStatus(formatTimeAgo(frame.timestamp));
    }

    async function showGallery() {
        await loadProcessedImages();
        if (state.processedImages.length > 0) {
            state.currentProcessedIndex = 0;
            showCurrentWorkflowImage();
        } else updateStatus('No processed images');
    }

    // Show image immediately, then load workflow details async
    function showCurrentWorkflowImage() {
        const img = state.processedImages[state.currentProcessedIndex];
        if (!img) return;
        
        const workflow = state.workflows[state.currentWorkflowIndex];
        const cacheKey = `${img.id}-${workflow}`;
        
        // Show fallback immediately (thumbnail/original in B&W)
        elements.overlay.style.display = 'block';
        elements.overlay.src = img.thumbnail || img.original_url;
        elements.overlay.style.filter = 'grayscale(1) brightness(0.7)';
        
        // Handle temp images with local workflow data
        if (img.isTemp) {
            const wfData = img.workflows?.find(w => w.name === workflow);
            if (img.uploadStatus === 'uploading') {
                updateStatus('Uploading...');
            } else if (img.uploadStatus === 'failed') {
                updateStatus('Upload failed');
                elements.overlay.style.filter = 'grayscale(1) brightness(0.4)';
            } else if (wfData) {
                if (wfData.status === 'pending') {
                    updateStatus(`${workflow}: Waiting...`);
                } else if (wfData.status === 'starting') {
                    updateStatus(`${workflow}: Starting...`);
                } else if (wfData.status === 'processing') {
                    updateStatus(`${workflow}: Processing...`);
                } else if (wfData.status === 'failed' || wfData.status === 'error') {
                    updateStatus(`${workflow}: Failed`);
                    elements.overlay.style.filter = 'grayscale(1) brightness(0.4)';
                } else if (wfData.status === 'completed' && wfData.job_id) {
                    elements.overlay.src = `/processor/artifact/${wfData.job_id}/visualizer`;
                    elements.overlay.style.filter = 'none';
                    updateStatus(`${workflow}: Ready`);
                }
            }
            return;
        }
        
        updateStatus(`${workflow}: Loading...`);
        
        // Check cache first - if cached and ready, show immediately
        if (state.workflowCache.has(cacheKey)) {
            const cached = state.workflowCache.get(cacheKey);
            if (cached.status === 'ready' && cached.url) {
                elements.overlay.src = cached.url;
                elements.overlay.style.filter = 'none';
                updateStatus(`${workflow}: Ready`);
                return;
            }
        }
        
        // Skip if already loading this combo
        if (state.loadingImages.has(cacheKey)) return;
        
        // Start async load in background
        loadWorkflowDetailsAsync(img, workflow, cacheKey);
    }

    // Async background loader
    async function loadWorkflowDetailsAsync(img, workflow, cacheKey) {
        state.loadingImages.add(cacheKey);
        
        try {
            const res = await fetchWithTimeout(`/processor/image/${img.id}/details`, {}, FETCH_TIMEOUT);
            if (!res.ok) throw new Error('Failed to fetch details');
            
            const details = await res.json();
            const workflowData = details.workflows?.find(w => w.name === workflow);
            
            // Check if user is still viewing this image/workflow
            const currentImg = state.processedImages[state.currentProcessedIndex];
            const currentWorkflow = state.workflows[state.currentWorkflowIndex];
            const stillRelevant = currentImg?.id === img.id && currentWorkflow === workflow;
            
            if (!workflowData) {
                state.workflowCache.set(cacheKey, { status: 'idle', url: null });
                if (stillRelevant) {
                    updateStatus(`${workflow}: Not processed`);
                }
                return;
            }
            
            state.workflowCache.set(cacheKey, {
                status: workflowData.status,
                url: workflowData.job_id ? `/processor/artifact/${workflowData.job_id}/visualizer` : null
            });
            
            if (!stillRelevant) return;
            
            if (workflowData.status === 'completed' && workflowData.job_id) {
                elements.overlay.src = `/processor/artifact/${workflowData.job_id}/visualizer`;
                elements.overlay.style.filter = 'none';
                updateStatus(`${workflow}: Ready`);
            } else if (workflowData.status === 'processing' || workflowData.status === 'pending') {
                updateStatus(`${workflow}: Processing...`);
            } else if (workflowData.status === 'failed' || workflowData.status === 'error') {
                elements.overlay.style.filter = 'grayscale(1) brightness(0.5)';
                updateStatus(`${workflow}: Error`);
            } else {
                updateStatus(`${workflow}: ${workflowData.status || 'Unknown'}`);
            }
        } catch (e) {
            console.error('Failed to fetch workflow details:', e);
            // Only update status if still viewing this image
            const currentImg = state.processedImages[state.currentProcessedIndex];
            const currentWorkflow = state.workflows[state.currentWorkflowIndex];
            if (currentImg?.id === img.id && currentWorkflow === workflow) {
                updateStatus(`${workflow}: Unavailable`);
            }
        } finally {
            state.loadingImages.delete(cacheKey);
        }
    }

    function scrollGallery(delta) {
        if (state.processedImages.length === 0) return;
        state.currentProcessedIndex += delta;
        if (state.currentProcessedIndex < 0) state.currentProcessedIndex = 0;
        if (state.currentProcessedIndex >= state.processedImages.length) state.currentProcessedIndex = state.processedImages.length - 1;
        showCurrentWorkflowImage();
    }

    function scrollWorkflows(delta) {
        if (state.processedImages.length === 0) return;
        state.currentWorkflowIndex += delta;
        if (state.currentWorkflowIndex < 0) state.currentWorkflowIndex = state.workflows.length - 1;
        if (state.currentWorkflowIndex >= state.workflows.length) state.currentWorkflowIndex = 0;
        showCurrentWorkflowImage();
        saveSettings();
    }

    function hideOverlay() {
        elements.overlay.style.display = 'none';
        if (elements.timelineBar) elements.timelineBar.classList.remove('visible');
        updateStatus('');
    }

    async function processFrame() {
        if (state.frames.length === 0) return;
        const frameIdx = getCurrentFrameIndex();
        const frame = state.frames[frameIdx] || state.frames[0];
        
        // Generate a temporary ID for immediate display
        const tempId = 'temp_' + Date.now();
        const tempImage = {
            id: tempId,
            timestamp: Date.now(),
            original_url: frame.dataUrl,
            thumbnail: frame.dataUrl,
            isTemp: true,
            uploadStatus: 'uploading',
            workflows: state.workflows.map(w => ({ name: w, status: 'pending' }))
        };
        
        // Add to gallery immediately
        state.processedImages.unshift(tempImage);
        state.currentProcessedIndex = 0;
        
        // Switch to gallery immediately if auto-gallery is on
        if (state.autoGallery) {
            state.currentMode = 'gallery';
            state.hoveredElement = 'scroll-images';
            state.activeControl = 'scroll-images';
            showGallery();
            updateUI();
        }
        
        updateStatus('Uploading...');
        
        // Do all backend operations asynchronously
        (async () => {
            try {
                const blob = await fetch(frame.dataUrl).then(r => r.blob());
                const formData = new FormData();
                formData.append('image', blob, 'frame.jpg');
                
                const uploadRes = await fetchWithTimeout('/processor/upload', { method: 'POST', body: formData }, FETCH_TIMEOUT);
                const uploadData = await uploadRes.json();
                
                if (uploadData.status === 'ok' || uploadData.success) {
                    const imageId = uploadData.image_id;
                    
                    // Update the temp image with real ID
                    tempImage.id = imageId;
                    tempImage.isTemp = false;
                    tempImage.uploadStatus = 'uploaded';
                    
                    // Update gallery if we're viewing this image
                    if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                        showCurrentWorkflowImage();
                    }
                    
                    updateStatus('Uploaded');
                    
                    // Start workflows one by one, updating status as they start
                    for (const workflow of state.workflows) {
                        try {
                            // Update status to show which workflow is starting
                            const wfEntry = tempImage.workflows.find(w => w.name === workflow);
                            if (wfEntry) wfEntry.status = 'starting';
                            
                            if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                                updateStatus(`${workflow}: Starting...`);
                            }
                            
                            const response = await fetchWithTimeout('/processor/run_workflow', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ image_id: imageId, workflow_name: workflow })
                            }, FETCH_TIMEOUT);
                            
                            const result = await response.json();
                            if (result.job_id) {
                                if (wfEntry) {
                                    wfEntry.job_id = result.job_id;
                                    wfEntry.status = 'processing';
                                }
                                
                                // Update cache
                                const cacheKey = `${imageId}-${workflow}`;
                                state.workflowCache.set(cacheKey, {
                                    status: 'processing',
                                    url: null,
                                    job_id: result.job_id
                                });
                            }
                        } catch (e) {
                            console.error(`Workflow ${workflow} failed to start:`, e);
                            const wfEntry = tempImage.workflows.find(w => w.name === workflow);
                            if (wfEntry) wfEntry.status = 'failed';
                        }
                    }
                    
                    if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                        updateStatus('All workflows started');
                    }
                    
                    // Now poll for workflow completion one by one
                    pollWorkflowCompletion(tempImage);
                }
            } catch (e) { 
                console.error('Upload failed:', e);
                tempImage.uploadStatus = 'failed';
                if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                    updateStatus('Upload failed');
                }
            }
        })();
    }
    
    // Poll for workflow completion status
    async function pollWorkflowCompletion(imageEntry) {
        const checkInterval = 5000; // Check every 5 seconds
        const maxAttempts = 60; // Max 5 minutes
        let attempts = 0;
        
        const checkWorkflows = async () => {
            if (attempts >= maxAttempts) return;
            attempts++;
            
            try {
                const res = await fetchWithTimeout(`/processor/image/${imageEntry.id}/details`, {}, FETCH_TIMEOUT);
                if (!res.ok) return;
                
                const details = await res.json();
                
                for (const workflow of imageEntry.workflows) {
                    if (workflow.status === 'completed' || workflow.status === 'failed') continue;
                    
                    const backendWorkflow = details.workflows?.find(w => w.name === workflow.name);
                    if (backendWorkflow) {
                        workflow.status = backendWorkflow.status;
                        workflow.job_id = backendWorkflow.job_id;
                        
                        // Update cache
                        const cacheKey = `${imageEntry.id}-${workflow.name}`;
                        state.workflowCache.set(cacheKey, {
                            status: backendWorkflow.status,
                            url: backendWorkflow.job_id ? `/processor/artifact/${backendWorkflow.job_id}/visualizer` : null,
                            job_id: backendWorkflow.job_id
                        });
                        
                        // Update display if viewing this image
                        if (state.currentMode === 'gallery' && 
                            state.processedImages[state.currentProcessedIndex]?.id === imageEntry.id &&
                            state.workflows[state.currentWorkflowIndex] === workflow.name) {
                            showCurrentWorkflowImage();
                        }
                    }
                }
                
                // Check if all workflows are done
                const allDone = imageEntry.workflows.every(w => 
                    w.status === 'completed' || w.status === 'failed' || w.status === 'error'
                );
                
                if (!allDone) {
                    setTimeout(checkWorkflows, checkInterval);
                }
            } catch (e) {
                console.error('Workflow status check failed:', e);
                setTimeout(checkWorkflows, checkInterval);
            }
        };
        
        setTimeout(checkWorkflows, checkInterval);
    }

    async function loadProcessedImages() {
        try {
            const res = await fetchWithTimeout('/processor/images', {}, FETCH_TIMEOUT);
            const data = await res.json();
            state.processedImages = data.images || [];
        } catch (e) { 
            console.error('Load error:', e);
            state.processedImages = [];
        }
    }

    async function sendToPlotter() {
        const img = state.processedImages[state.currentProcessedIndex];
        if (!img) return;
        
        const workflow = state.workflows[state.currentWorkflowIndex];
        updateStatus('Getting job info...');
        
        try {
            // Get job_id from cache or fetch from backend
            const cacheKey = `${img.id}-${workflow}`;
            let jobId = null;
            
            if (state.workflowCache.has(cacheKey)) {
                const cached = state.workflowCache.get(cacheKey);
                jobId = cached.job_id;
            }
            
            // If not in cache, fetch details
            if (!jobId) {
                const res = await fetchWithTimeout(`/processor/image/${img.id}/details`, {}, FETCH_TIMEOUT);
                if (res.ok) {
                    const details = await res.json();
                    const wfData = details.workflows?.find(w => w.name === workflow);
                    if (wfData) {
                        jobId = wfData.job_id;
                        // Update cache
                        state.workflowCache.set(cacheKey, {
                            status: wfData.status,
                            url: wfData.job_id ? `/processor/artifact/${wfData.job_id}/visualizer` : null,
                            job_id: wfData.job_id
                        });
                    }
                }
            }
            
            if (!jobId) {
                updateStatus('No job found');
                return;
            }
            
            updateStatus('Getting artifacts...');
            
            // Fetch status to get artifacts with file_hash (like processor.js does)
            const statusRes = await fetchWithTimeout(`/processor/status?ids=${jobId}`, {}, FETCH_TIMEOUT);
            if (!statusRes.ok) {
                updateStatus('Failed to get artifacts');
                return;
            }
            
            const jobsMeta = await statusRes.json();
            const artifacts = jobsMeta[0]?.artifacts || [];
            
            // Filter for slicers and sort by timestamp
            const slicers = artifacts
                .filter(a => a.slug && a.slug.startsWith('slicer'))
                .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
            
            if (slicers.length === 0) {
                updateStatus('No slicer data found');
                return;
            }
            
            updateStatus('Sending to plotter...');
            
            // Send each slicer file to plotter
            for (const s of slicers) {
                await fetchWithTimeout('/processor/enqueue_to_plotter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        job_id: jobId, 
                        slug: s.slug, 
                        file_hash: s.hash 
                    })
                }, FETCH_TIMEOUT);
            }
            
            updateStatus(`Sent ${slicers.length} file(s) to plotter`);
            state.activeControl = null;
            updateUI();
        } catch (e) { 
            updateStatus('Plot error'); 
            console.error(e);
        }
    }

    function updateStatus(text) { elements.status.textContent = text; }

    function updateUI() {
        Object.keys(elements.modes).forEach(mode => {
            const btn = elements.modes[mode];
            if (!btn) return;
            const isActive = mode === state.currentMode;
            const isHovered = mode === state.hoveredElement;
            btn.classList.remove('blue', 'green');
            if (isActive) btn.classList.add('green');
            if (isHovered && !state.activeControl) btn.classList.add('blue');
        });
        
        elements.bottomBar.innerHTML = '';
        const controls = getCurrentControls();
        controls.forEach(control => {
            const btn = document.createElement('button');
            btn.className = 'control-btn';
            btn.textContent = formatLabel(control);
            const isActive = control === state.activeControl;
            const isHovered = control === state.hoveredElement;
            
            if (isHovered && !state.activeControl) {
                if (OPTION_CONTROLS.includes(control)) btn.classList.add('yellow');
                else if (ACTION_CONTROLS.includes(control)) btn.classList.add('red');
                else btn.classList.add('blue');
            }
            if (isActive) btn.classList.add('green');
            elements.bottomBar.appendChild(btn);
        });
        
        if (elements.timelineBar && state.currentMode !== 'timeline') {
            elements.timelineBar.classList.remove('visible');
        }
    }

    function formatLabel(control) {
        const labels = {
            'zoom': `Zoom: ${state.zoomLevel.toFixed(1)}x`,
            'pan-x': `Pan X: ${state.panX}px`,
            'pan-y': `Pan Y: ${state.panY}px`,
            'switch-camera': getCurrentCameraName(),
            'scroll-timeline': 'Scroll',
            'process': 'Process',
            'auto-gallery': `Auto: ${state.autoGallery ? 'ON' : 'OFF'}`,
            'scroll-images': 'Images',
            'scroll-workflows': state.workflows[state.currentWorkflowIndex] || 'Style',
            'send-plotter': 'Plot',
            'y-start': `Y-Start: ${state.settings.yStart}%`,
            'y-end': `Y-End: ${state.settings.yEnd}%`,
            'fullscreen': state.isFullscreen ? 'Exit Full' : 'Fullscreen'
        };
        return labels[control] || control;
    }
})();
