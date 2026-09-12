import React, { useState } from 'react';
import { 
  X, 
  Terminal, 
  Wifi, 
  WifiOff, 
  Trash2 
} from 'lucide-react';
import { TRANSLATIONS } from '../utils/i18n';

export function WebSocketLogsModal({
  isOpen,
  onClose,
  wsStatus,
  wsUrl,
  onUpdateWsUrl,
  onConnect,
  onDisconnect,
  logs = [],
  onClearLogs,
  lang = 'en',
  darkMode = false,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const [inputUrl, setInputUrl] = useState(wsUrl);

  if (!isOpen) return null;

  const handleSaveUrl = (e) => {
    e.preventDefault();
    if (inputUrl.trim()) {
      onUpdateWsUrl(inputUrl.trim());
      onConnect(inputUrl.trim());
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className={`w-full max-w-xl border rounded-lg shadow-xl overflow-hidden transition-colors ${
        darkMode ? 'bg-[#111827] border-slate-800 text-white' : 'bg-white border-slate-300 text-slate-900'
      }`}>
        {/* Header */}
        <div className={`p-4 flex items-center justify-between ${
          darkMode ? 'bg-[#090d16] text-white border-b border-slate-800' : 'bg-slate-900 text-white'
        }`}>
          <div className="flex items-center gap-2">
            <Terminal className="size-4 text-amber-400" strokeWidth={1.5} />
            <h2 className="text-sm font-bold uppercase tracking-wider">{t.wsDiagnostics}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white rounded-md hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        </div>

        {/* Server Endpoint Form */}
        <div className={`p-4 border-b ${
          darkMode ? 'bg-[#0b0f19] border-slate-800' : 'bg-slate-50 border-slate-200'
        }`}>
          <form onSubmit={handleSaveUrl} className="flex gap-2">
            <input
              type="text"
              value={inputUrl}
              onChange={(e) => setInputUrl(e.target.value)}
              placeholder="ws://localhost:8000/ws"
              className={`flex-1 px-3 py-1.5 text-xs font-mono rounded-md border outline-none font-medium ${
                darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'border-slate-300 bg-white text-slate-900 focus:border-slate-500'
              }`}
            />
            {wsStatus === 'connected' ? (
              <button
                type="button"
                onClick={onDisconnect}
                className="px-3 py-1.5 rounded-md border border-rose-300 bg-rose-50 text-rose-700 text-xs font-semibold hover:bg-rose-100 transition-colors cursor-pointer flex items-center gap-1"
              >
                <WifiOff className="size-3.5" strokeWidth={1.5} /> {t.disconnect}
              </button>
            ) : (
              <button
                type="submit"
                className="px-3 py-1.5 rounded-md bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1"
              >
                <Wifi className="size-3.5" strokeWidth={1.5} /> {t.connect}
              </button>
            )}
          </form>
        </div>

        {/* Logs Feed */}
        <div className="p-4 text-xs">
          <div className="flex items-center justify-between mb-2">
            <span className={`font-bold uppercase tracking-wider text-[11px] ${
              darkMode ? 'text-slate-300' : 'text-slate-700'
            }`}>{t.activityLog} ({logs.length})</span>
            <button
              onClick={onClearLogs}
              className={`flex items-center gap-1 cursor-pointer text-[11px] font-medium ${
                darkMode ? 'text-slate-400 hover:text-rose-400' : 'text-slate-500 hover:text-rose-600'
              }`}
            >
              <Trash2 className="size-3" strokeWidth={1.5} /> {t.clear}
            </button>
          </div>

          <div className="rounded-md border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] text-slate-200 max-h-56 overflow-y-auto space-y-2">
            {logs.length === 0 ? (
              <div className="text-slate-500 italic py-4 text-center">
                No WebSocket events recorded.
              </div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="border-b border-slate-800 pb-1.5 last:border-none">
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mb-0.5">
                    <span className="uppercase font-semibold text-amber-400">[{log.type}]</span>
                    <span>{new Date(log.timestamp).toLocaleTimeString()}</span>
                  </div>
                  <div className="text-emerald-400">{log.text}</div>
                  {log.payload && (
                    <pre className="mt-1 p-1.5 rounded bg-slate-900 text-[10px] text-slate-300 overflow-x-auto">
                      {JSON.stringify(log.payload, null, 2)}
                    </pre>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
