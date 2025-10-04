// WebSocket polyfill for Node.js environment
if (typeof global !== 'undefined' && !global.WebSocket) {
  const WebSocket = require('ws');
  global.WebSocket = WebSocket;
  global.window = global.window || {};
  global.window.WebSocket = WebSocket;
}
