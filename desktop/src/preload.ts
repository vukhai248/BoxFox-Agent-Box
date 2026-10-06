/**
 * Preload of the desktop shell. `contextIsolation` stays on and `nodeIntegration`
 * off; the UI only sees this narrow bridge.
 */

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('boxfoxDesktop', {
  version: process.versions.electron,
  platform: process.platform,
  identity: () => ipcRenderer.invoke('boxfox:identity'),
})
