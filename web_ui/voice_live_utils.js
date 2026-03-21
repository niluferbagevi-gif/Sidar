(function initVoiceLiveUtils(globalScope) {
  const labels = {
    idle: 'Bekleniyor',
    ready: 'Hazır',
    chunk: 'Dinleniyor',
    speech_start: 'Konuşma algılandı',
    speech_end: 'Konuşma bitti',
    processed: 'İşlendi',
    cancelled: 'İptal edildi',
    unknown: 'Bilinmeyen durum',
  };

  function getVoiceLiveDefaults() {
    return {
      lastTranscript: '',
      lastState: 'idle',
      summary: 'Ses websocket tanılama verisi bekleniyor.',
      diagnostics: 'Henüz ek tanı verisi yok.',
      badgeClass: 'idle',
      badgeLabel: 'Bekleniyor',
      log: [],
    };
  }

  function getVoiceBadgeMeta(stateKey, payload = {}) {
    const normalized = String(stateKey || 'idle').trim().toLowerCase() || 'idle';
    if (payload.error) return { badgeClass: 'error', badgeLabel: 'Hata' };
    if (payload.voice_interruption || normalized === 'cancelled') return { badgeClass: 'error', badgeLabel: 'Kesildi' };
    if (normalized === 'processed' || payload.assistant_turn === 'completed' || payload.done) {
      return { badgeClass: 'complete', badgeLabel: 'Tamamlandı' };
    }
    if (payload.transcript || payload.assistant_turn === 'started') {
      return { badgeClass: 'processing', badgeLabel: 'İşleniyor' };
    }
    if (normalized === 'ready' || normalized === 'chunk' || normalized === 'speech_start' || normalized === 'speech_end') {
      return { badgeClass: 'listening', badgeLabel: 'Canlı' };
    }
    return { badgeClass: 'idle', badgeLabel: labels[normalized] || 'Bekleniyor' };
  }

  function buildVoiceDiagnosticsText(payload = {}) {
    const parts = [];
    if (payload.buffered_bytes !== undefined) parts.push(`buffer ${payload.buffered_bytes} B`);
    if (payload.sequence !== undefined) parts.push(`seq ${payload.sequence}`);
    if (payload.audio_sequence !== undefined) parts.push(`audio #${payload.audio_sequence}`);
    if (payload.assistant_turn_id !== undefined) parts.push(`tur ${payload.assistant_turn_id}`);
    if (payload.provider) parts.push(`sağlayıcı ${payload.provider}`);
    if (payload.language) parts.push(`dil ${payload.language}`);
    if (payload.audio_mime_type) parts.push(payload.audio_mime_type);
    if (payload.last_interrupt_reason) parts.push(`kesinti ${payload.last_interrupt_reason}`);
    if (payload.cancelled_audio_sequences !== undefined) parts.push(`iptal ses ${payload.cancelled_audio_sequences}`);
    if (payload.auto_commit_ready !== undefined) parts.push(payload.auto_commit_ready ? 'otomatik commit hazır' : 'otomatik commit bekliyor');
    if (payload.interrupt_ready !== undefined) parts.push(payload.interrupt_ready ? 'barge-in hazır' : 'barge-in pasif');
    if (payload.error) parts.push(`hata ${payload.error}`);
    return parts.length ? parts.join(' · ') : 'Henüz ek tanı verisi yok.';
  }

  function appendVoiceLog(log, label, value) {
    const next = Array.isArray(log) ? [...log] : [];
    next.unshift({ label, value });
    return next.slice(0, 8);
  }

  globalScope.SidarVoiceLiveUtils = {
    VOICE_STATE_LABELS: labels,
    getVoiceLiveDefaults,
    getVoiceBadgeMeta,
    buildVoiceDiagnosticsText,
    appendVoiceLog,
  };
})(typeof window !== 'undefined' ? window : globalThis);