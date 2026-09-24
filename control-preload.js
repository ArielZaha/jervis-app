// The control overlay's only link to the rest of Jervis: state in, button presses out.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('control', {
  onEvent: (callback) => ipcRenderer.on('control-event', (_event, message) => callback(message)),
  act: (action) => ipcRenderer.send('control-overlay-action', action),        // 'stop' | 'pause' | 'resume'
  answer: (id, allow) => ipcRenderer.send('control-overlay-answer', { id, allow }),
  hovering: (on) => ipcRenderer.send('control-overlay-hover', Boolean(on)),   // let clicks reach the buttons
});
