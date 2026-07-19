// TikTok Video Creator - Frontend JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // State
    let videoFile = null;
    let avatarFile = null;
    let isProcessing = false;

    // DOM Elements
    const btnVideo = document.getElementById('btn-video');
    const videoInput = document.getElementById('video-input');
    const videoLabel = document.getElementById('video-label');
    
    const btnAvatar = document.getElementById('btn-avatar');
    const avatarInput = document.getElementById('avatar-input');
    const avatarLabel = document.getElementById('avatar-label');
    const btnAvatarClear = document.getElementById('btn-avatar-clear');
    
    const authorInput = document.getElementById('author-input');
    const introInput = document.getElementById('intro-input');
    const bodyInput = document.getElementById('body-input');
    const charCounter = document.getElementById('char-counter');
    
    const speedSlider = document.getElementById('speed-slider');
    const speedLabel = document.getElementById('speed-label');
    
    const sizeSlider = document.getElementById('size-slider');
    const sizeLabel = document.getElementById('size-label');
    
    const posSlider = document.getElementById('pos-slider');
    const posLabel = document.getElementById('pos-label');
    
    const gpuCheckbox = document.getElementById('gpu-checkbox');
    const encoderLabel = document.getElementById('encoder-label');
    
    const generateBtn = document.getElementById('generate-btn');
    const statusLabel = document.getElementById('status-label');
    const percentLabel = document.getElementById('percent-label');
    const progressFill = document.getElementById('progress-fill');

    // Initialize
    updateCharCount();
    detectGPU();

    // Event Listeners
    
    // Video selection
    btnVideo.addEventListener('click', () => videoInput.click());
    videoInput.addEventListener('change', handleVideoSelect);
    
    // Avatar selection
    btnAvatar.addEventListener('click', () => avatarInput.click());
    avatarInput.addEventListener('change', handleAvatarSelect);
    btnAvatarClear.addEventListener('click', clearAvatar);
    
    // Character counter
    introInput.addEventListener('input', updateCharCount);
    bodyInput.addEventListener('input', updateCharCount);
    
    // Sliders
    speedSlider.addEventListener('input', updateSpeedLabel);
    sizeSlider.addEventListener('input', updateSizeLabel);
    posSlider.addEventListener('input', updatePosLabel);
    
    // Generate button
    generateBtn.addEventListener('click', handleGenerate);

    // Functions
    
    function handleVideoSelect(e) {
        const file = e.target.files[0];
        if (file) {
            videoFile = file;
            videoLabel.textContent = `✅  ${file.name}`;
            videoLabel.classList.add('success');
        }
    }
    
    function handleAvatarSelect(e) {
        const file = e.target.files[0];
        if (file) {
            avatarFile = file;
            avatarLabel.textContent = `✅  ${file.name}`;
            avatarLabel.classList.add('success');
        }
    }
    
    function clearAvatar() {
        avatarFile = null;
        avatarInput.value = '';
        avatarLabel.textContent = 'Padrão';
        avatarLabel.classList.remove('success');
    }
    
    function updateCharCount() {
        const introCount = introInput.value.length;
        const bodyCount = bodyInput.value.length;
        const total = introCount + bodyCount;
        charCounter.textContent = `${total} caracteres (Card: ${introCount}, Legendas: ${bodyCount})`;
    }
    
    function updateSpeedLabel() {
        const val = parseInt(speedSlider.value);
        const sign = val >= 0 ? '+' : '';
        speedLabel.textContent = `Velocidade (${sign}${val}%):`;
    }
    
    function updateSizeLabel() {
        const val = parseInt(sizeSlider.value);
        sizeLabel.textContent = `Fonte (${val}):`;
    }
    
    function updatePosLabel() {
        const val = parseInt(posSlider.value);
        posLabel.textContent = `Posição Y (${val}):`;
    }
    
    async function detectGPU() {
        try {
            const response = await fetch('/api/detect-gpu');
            const contentType = response.headers.get('content-type');
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Expected JSON response');
            }
            
            const data = await response.json();
            if (data.encoder) {
                const encoderNames = {
                    'h264_nvenc': 'NVIDIA NVENC (Aceleração por Hardware)',
                    'h264_amf': 'AMD AMF (Aceleração por Hardware)',
                    'h264_qsv': 'Intel QSV (Aceleração por Hardware)',
                    'h264_mf': 'Windows Media Foundation (Aceleração por Hardware)',
                    'libx264': 'CPU / libx264 (Sem Aceleração)'
                };
                encoderLabel.textContent = `GPU: ${encoderNames[data.encoder] || data.encoder}`;
                
                if (data.encoder === 'libx264') {
                    gpuCheckbox.checked = false;
                    gpuCheckbox.disabled = true;
                }
            }
        } catch (error) {
            console.error('GPU detection error:', error);
            encoderLabel.textContent = 'GPU: Não disponível';
            gpuCheckbox.checked = false;
            gpuCheckbox.disabled = true;
        }
    }
    
    async function handleGenerate() {
        if (isProcessing) return;
        
        // Validation
        if (!videoFile) {
            alert('Seleciona um vídeo de fundo primeiro!');
            return;
        }
        
        const intro = introInput.value.trim();
        const body = bodyInput.value.trim();
        
        if (!intro && !body) {
            alert('Escreve o texto da história primeiro!');
            return;
        }
        
        // Get form data
        const voiceType = document.querySelector('input[name="voice"]:checked').value;
        const wordsPerCue = document.getElementById('words-select').value;
        const colorSelect = document.getElementById('color-select').value;
        const animType = document.getElementById('anim-select').value;
        const fontSize = parseInt(sizeSlider.value);
        const positionY = parseInt(posSlider.value);
        const useGPU = gpuCheckbox.checked;
        const speedVal = parseInt(speedSlider.value);
        const sign = speedVal >= 0 ? '+' : '';
        const voiceRate = `${sign}${speedVal}%`;
        
        // Color mapping
        const colorMap = {
            'Amarelo Néon': '&H0000F2FF',
            'Verde Néon': '&H0000FF33',
            'Ciano Néon': '&H00FFFF00',
            'Rosa Néon': '&H00FF33FF',
            'Branco (Sem Destaque)': null
        };
        const activeColor = colorMap[colorSelect] || '&H0000F2FF';
        
        // Prepare form data
        const formData = new FormData();
        formData.append('video', videoFile);
        formData.append('author', authorInput.value.trim());
        formData.append('intro', intro);
        formData.append('body', body);
        formData.append('voice_type', voiceType);
        formData.append('words_per_cue', wordsPerCue);
        formData.append('active_color', activeColor || '');
        formData.append('font_size', fontSize);
        formData.append('position_y', positionY);
        formData.append('use_gpu', useGPU);
        formData.append('anim_type', animType);
        formData.append('voice_rate', voiceRate);
        
        if (avatarFile) {
            formData.append('avatar', avatarFile);
        }
        
        // Start processing
        isProcessing = true;
        generateBtn.disabled = true;
        updateProgress('🎙️ A gerar áudio TTS...', 10);
        
        try {
            const response = await fetch('/api/generate', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Erro na geração do vídeo');
            }
            
            // Download the video
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'tiktok_video.mp4';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            updateProgress('✅ Vídeo criado com sucesso!', 100);
            setTimeout(() => {
                updateProgress('Pronto', 0);
            }, 2500);
            
        } catch (error) {
            console.error('Error:', error);
            alert(`Erro: ${error.message}`);
            updateProgress('❌ Erro na geração', 0);
        } finally {
            isProcessing = false;
            generateBtn.disabled = false;
        }
    }
    
    function updateProgress(message, percent) {
        statusLabel.textContent = message;
        progressFill.style.width = `${percent}%`;
        percentLabel.textContent = `${percent}%`;
        
        if (percent >= 100) {
            percentLabel.classList.remove('active');
            percentLabel.classList.add('success');
        } else if (percent > 0) {
            percentLabel.classList.remove('success');
            percentLabel.classList.add('active');
        } else {
            percentLabel.classList.remove('active', 'success');
        }
    }
});
