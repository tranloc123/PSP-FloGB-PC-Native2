const { ipcRenderer } = require('electron');

window.SCBD = {
  report(kind, payload) {
    try { ipcRenderer.send('scbd-live-report', { kind: String(kind || ''), payload }); } catch (_) {}
  }
};

(() => {
  if (window.__SCBD_DEV_BOOTSTRAP__) return;
  window.__SCBD_DEV_BOOTSTRAP__ = true;
  const dispatch = (name, detail) => { try { window.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const toFullBinary = (ab) => {
    try {
      const u8 = new Uint8Array(ab);
      return { len:u8.byteLength, sampleBytes:u8.byteLength, full:true, buffer:u8.slice().buffer };
    } catch (e) { return { error:String(e) }; }
  };
  try {
    const NativeWS = window.WebSocket;
    if (NativeWS && !NativeWS.__SCBD_WRAPPED__) {
      class SCBDWebSocket extends NativeWS {
        constructor(...args) {
          super(...args);
          dispatch('__SCBD_WS_META__', {event:'connect', url:String(args[0] || '')});
          this.addEventListener('open', () => dispatch('__SCBD_WS_META__', {event:'open', url:this.url || String(args[0] || '')}));
          this.addEventListener('close', e => dispatch('__SCBD_WS_META__', {event:'close', url:this.url || String(args[0] || ''), code:e.code, reason:e.reason || ''}));
          this.addEventListener('message', async e => {
            try {
              if (typeof e.data === 'string') return dispatch('__SCBD_WS_MESSAGE__', {kind:'text', data:e.data});
              if (e.data instanceof ArrayBuffer) return dispatch('__SCBD_WS_MESSAGE__', {kind:'binary', data:toFullBinary(e.data)});
              if (ArrayBuffer.isView(e.data)) {
                const ab=e.data.buffer.slice(e.data.byteOffset,e.data.byteOffset+e.data.byteLength);
                return dispatch('__SCBD_WS_MESSAGE__',{kind:'binary',data:toFullBinary(ab)});
              }
              if (typeof Blob !== 'undefined' && e.data instanceof Blob) {
                const ab=await e.data.arrayBuffer(); return dispatch('__SCBD_WS_MESSAGE__',{kind:'binary',data:toFullBinary(ab)});
              }
            } catch (err) { dispatch('__SCBD_BOOT_ERR__','ws-message '+err); }
          });
        }
      }
      Object.defineProperty(SCBDWebSocket,'__SCBD_WRAPPED__',{value:true});
      window.WebSocket = SCBDWebSocket;
    }
  } catch (e) { dispatch('__SCBD_BOOT_ERR__','ws-hook '+e); }
  try { window.SCBD.report('BOOT','document-start hooks installed'); } catch (_) {}
})();
