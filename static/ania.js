/**
 * ania.js - Controlador do Chatbot e Assistente de Voz Ania
 * Ateliê Haiti - 100% Gratuito (Web Speech API)
 */

(function () {
  'use strict';

  // ── Elementos do DOM ──────────────────────────────────────────────────
  const fab = document.getElementById('ania-fab');
  const chatWindow = document.getElementById('ania-chat-window');
  const overlay = document.getElementById('ania-modal-overlay');
  const btnClose = document.getElementById('ania-btn-close');
  const btnClear = document.getElementById('ania-btn-clear');
  const btnSound = document.getElementById('ania-btn-sound');
  const btnMic = document.getElementById('ania-btn-mic');
  const btnSend = document.getElementById('ania-btn-send');
  const inputEl = document.getElementById('ania-input');
  const messagesContainer = document.getElementById('ania-messages');
  const suggestionsBar = document.getElementById('ania-suggestions-bar');
  const voiceListeningBox = document.getElementById('ania-voice-listening');
  const voiceStatusText = document.getElementById('ania-voice-status-text');

  if (!fab || !chatWindow) return;

  // ── Estado Global da Assistente ───────────────────────────────────────
  let isListening = false;
  let isSpeaking = false;
  let isVoiceMuted = localStorage.getItem('ania_voice_muted') === 'true';
  let recognition = null;
  let synth = window.speechSynthesis || null;

  // ── Inicialização do Web Speech API: Reconhecimento de Voz (STT) ──────
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = function () {
      isListening = true;
      btnMic.classList.add('listening');
      if (voiceListeningBox) voiceListeningBox.classList.add('active');
      if (voiceStatusText) voiceStatusText.textContent = 'Ouvindo... Fale agora';
      pararFala();
    };

    recognition.onresult = function (event) {
      let interimTranscript = '';
      let finalTranscript = '';

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }

      if (interimTranscript && voiceStatusText) {
        voiceStatusText.textContent = `"${interimTranscript}"`;
      }

      if (finalTranscript) {
        inputEl.value = finalTranscript.trim();
        pararEscuta();
        enviarMensagem(finalTranscript.trim());
      }
    };

    recognition.onerror = function (event) {
      console.warn('Erro no reconhecimento de voz:', event.error);
      pararEscuta();
      if (event.error === 'not-allowed') {
        adicionarMensagemBot('⚠️ Permissão do microfone negada. Permita o microfone no seu navegador para falar com a Ania por voz.');
      }
    };

    recognition.onend = function () {
      pararEscuta();
    };
  } else {
    if (btnMic) {
      btnMic.title = 'Reconhecimento de voz não suportado neste navegador';
      btnMic.style.opacity = '0.5';
    }
  }

  function iniciarEscuta() {
    if (!recognition) {
      alert('Seu navegador não suporta reconhecimento de voz. Você pode digitar normalmente.');
      return;
    }
    try {
      recognition.start();
    } catch (e) {
      console.warn('Erro ao iniciar gravação:', e);
      pararEscuta();
    }
  }

  function pararEscuta() {
    isListening = false;
    if (btnMic) btnMic.classList.remove('listening');
    if (voiceListeningBox) voiceListeningBox.classList.remove('active');
    if (recognition) {
      try { recognition.stop(); } catch (e) {}
    }
  }

  function alternarEscuta() {
    if (isListening) {
      pararEscuta();
    } else {
      iniciarEscuta();
    }
  }

  // ── Inicialização do Web Speech API: Síntese de Voz (TTS) ────────────
  function atualizarBotaoSom() {
    if (!btnSound) return;
    if (isVoiceMuted) {
      btnSound.innerHTML = '🔇';
      btnSound.title = 'Áudio desativado (Clique para ativar fala da Ania)';
      btnSound.classList.remove('active');
    } else {
      btnSound.innerHTML = '🔊';
      btnSound.title = 'Áudio ativado (Ania responderá por voz)';
      btnSound.classList.add('active');
    }
  }

  function alternarSom() {
    isVoiceMuted = !isVoiceMuted;
    localStorage.setItem('ania_voice_muted', isVoiceMuted);
    atualizarBotaoSom();
    if (isVoiceMuted) {
      pararFala();
    }
  }

  function falarTexto(texto) {
    if (isVoiceMuted || !synth || !texto) return;

    pararFala();

    // Limpa marcações markdown e caracteres especiais para fala natural
    const textoLimpo = texto
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/[•\-\#\_]/g, ' ')
      .replace(/https?:\/\/\S+/g, '')
      .replace(/R\$\s*(\d+(?:[.,]\d+)?)/g, '$1 reais')
      .replace(/\s+/g, ' ')
      .trim();

    if (!textoLimpo) return;

    const utter = new SpeechSynthesisUtterance(textoLimpo);
    utter.lang = 'pt-BR';
    utter.rate = 1.05;
    utter.pitch = 1.0;

    // Tenta encontrar uma voz em português brasileiro
    const voices = synth.getVoices();
    const ptVoice = voices.find(v => v.lang === 'pt-BR' || v.lang.startsWith('pt')) || null;
    if (ptVoice) {
      utter.voice = ptVoice;
    }

    utter.onstart = function () {
      isSpeaking = true;
    };
    utter.onend = function () {
      isSpeaking = false;
    };
    utter.onerror = function () {
      isSpeaking = false;
    };

    try {
      synth.speak(utter);
    } catch (e) {
      console.warn('Erro na síntese de voz:', e);
    }
  }

  function pararFala() {
    if (synth && synth.speaking) {
      try { synth.cancel(); } catch (e) {}
    }
    isSpeaking = false;
  }

  // ── Abertura e Fechamento do Chat ─────────────────────────────────────
  function abrirChat() {
    chatWindow.classList.add('open');
    if (overlay) overlay.classList.add('open');
    if (fab) fab.style.display = 'none';
    setTimeout(() => {
      if (inputEl) inputEl.focus();
    }, 150);
  }

  function fecharChat() {
    chatWindow.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
    if (fab) fab.style.display = 'flex';
    pararEscuta();
    pararFala();
  }

  function limparHistorico() {
    pararFala();
    messagesContainer.innerHTML = '';
    renderizarSugestoes([
      '📦 Consultar estoque',
      '🧾 Pedidos pendentes',
      '📊 Ver alertas',
      '💰 Resumo financeiro',
      'Minhas permissões',
      'Ajuda'
    ]);
    adicionarMensagemBot('Histórico limpo! Como posso te ajudar agora?');
  }

  // ── Renderização de Mensagens ─────────────────────────────────────────
  function formatarMarkdown(txt) {
    if (!txt) return '';
    
    // Suporte a markdown links [Texto](url)
    let html = txt.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+|\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" class="btn-secondary" style="display:inline-block; padding:6px 14px; font-size:14px; text-decoration:none; margin:4px 0;">$1</a>');

    // Negrito, itálico e código
    html = html
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.06); padding:2px 6px; border-radius:4px; font-family:monospace; font-size:13px; color:var(--primary);">$1</code>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>');

    return `<p>${html}</p>`;
  }

  function adicionarMensagemUsuario(txt) {
    const div = document.createElement('div');
    div.className = 'ania-msg ania-msg-user';
    div.innerHTML = `
      <div class="ania-msg-bubble font-serif">
        <p>${txt.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>
      </div>
    `;
    messagesContainer.appendChild(div);
    scrollParaFinal();
  }

  function adicionarMensagemBot(htmlOuTexto, isDenied = false) {
    const div = document.createElement('div');
    div.className = `ania-msg ania-msg-bot ${isDenied ? 'denied' : ''}`;
    const formatted = formatarMarkdown(htmlOuTexto);
    div.innerHTML = `
      <div class="ania-msg-avatar">🧵</div>
      <div class="ania-msg-bubble">
        ${formatted}
      </div>
    `;
    messagesContainer.appendChild(div);
    scrollParaFinal();
  }

  function mostrarDigitando() {
    const div = document.createElement('div');
    div.id = 'ania-typing-indicator';
    div.className = 'ania-msg ania-msg-bot';
    div.innerHTML = `
      <div class="ania-msg-avatar">🧵</div>
      <div class="ania-msg-bubble" style="padding:10px 14px;">
        <div class="ania-typing-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    `;
    messagesContainer.appendChild(div);
    scrollParaFinal();
  }

  function removerDigitando() {
    const el = document.getElementById('ania-typing-indicator');
    if (el) el.remove();
  }

  function scrollParaFinal() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function renderizarSugestoes(sugestoes) {
    if (!suggestionsBar) return;
    suggestionsBar.innerHTML = '';
    if (!sugestoes || sugestoes.length === 0) return;

    sugestoes.forEach(s => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ania-chip';
      chip.textContent = s;
      chip.onclick = function () {
        enviarMensagem(s);
      };
      suggestionsBar.appendChild(chip);
    });
  }

  // ── Envio da Mensagem para a API Backend ──────────────────────────────
  async function enviarMensagem(texto) {
    const prompt = (texto || (inputEl ? inputEl.value : '')).trim();
    if (!prompt) return;

    if (inputEl) inputEl.value = '';
    adicionarMensagemUsuario(prompt);
    mostrarDigitando();

    try {
      const resp = await fetch('/api/ania/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt })
      });

      removerDigitando();

      if (resp.status === 401) {
        adicionarMensagemBot('🔒 Sua sessão expirou. Por favor, faça login novamente no sistema.', true);
        falarTexto('Sua sessão expirou. Por favor faça login novamente.');
        return;
      }

      const data = await resp.json();

      adicionarMensagemBot(data.reply || 'Operação concluída com sucesso.', Boolean(data.denied));
      
      if (data.voice_text) {
        falarTexto(data.voice_text);
      } else if (data.reply) {
        falarTexto(data.reply);
      }

      if (data.suggestions && data.suggestions.length > 0) {
        renderizarSugestoes(data.suggestions);
      }

      if (data.action) {
        if (data.action.type === 'navigate' && data.action.url) {
          setTimeout(() => {
            window.location.href = data.action.url;
          }, 1200);
        } else if (data.action.type === 'download' && data.action.url) {
          setTimeout(() => {
            const a = document.createElement('a');
            a.href = data.action.url;
            a.target = '_blank';
            if (data.action.filename) a.download = data.action.filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
          }, 600);
        }
      }
    } catch (err) {
      console.error('Erro na requisição da Ania:', err);
      removerDigitando();
      adicionarMensagemBot('⚠️ Houve um problema de conexão com o servidor. Tente novamente em instantes.');
    }
  }

  // ── Event Listeners ───────────────────────────────────────────────────
  if (fab) fab.addEventListener('click', abrirChat);
  if (btnClose) btnClose.addEventListener('click', fecharChat);
  if (overlay) overlay.addEventListener('click', fecharChat);
  if (btnClear) btnClear.addEventListener('click', limparHistorico);
  if (btnSound) btnSound.addEventListener('click', alternarSom);
  if (btnMic) btnMic.addEventListener('click', alternarEscuta);

  if (btnSend) {
    btnSend.addEventListener('click', () => enviarMensagem());
  }

  if (inputEl) {
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        enviarMensagem();
      }
    });
  }

  // Atalho global de teclado: Alt + A ou Ctrl + Space abre a Ania
  window.addEventListener('keydown', function (e) {
    if ((e.altKey && e.key.toLowerCase() === 'a') || (e.ctrlKey && e.code === 'Space')) {
      e.preventDefault();
      if (chatWindow.classList.contains('open')) {
        fecharChat();
      } else {
        abrirChat();
      }
    }
  });

  // Inicialização do estado de som
  atualizarBotaoSom();

  // Se o synth estiver carregando vozes assincronamente (Chrome/Safari)
  if (synth && synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = function () {
      synth.getVoices();
    };
  }
})();
