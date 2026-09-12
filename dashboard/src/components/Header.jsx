import React from 'react';
import { 
  Radio, 
  Sparkles, 
  Mic, 
  Trash2, 
  Terminal,
  Sun,
  Moon
} from 'lucide-react';
import { TRANSLATIONS } from '../utils/i18n';

export function Header({
  wsStatus = 'disconnected',
  activeView = 'table',
  onViewChange,
  onOpenVoiceSimulator,
  onOpenWsLogs,
  onQuickSimulate,
  onClearAllData,
  shipmentsCount = 0,
  lang = 'en',
  onToggleLang,
  darkMode = false,
  onToggleDarkMode,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;

  const renderWsIndicator = () => {
    switch (wsStatus) {
      case 'connected':
        return (
          <button
            onClick={onOpenWsLogs}
            className={`flex items-center gap-2 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors cursor-pointer ${
              darkMode 
                ? 'bg-slate-900 text-slate-300 border-slate-800 hover:bg-slate-800' 
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700/80'
            }`}
            title="WebSocket Connected (Click for live monitor)"
          >
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>{t.liveConnection}</span>
          </button>
        );
      case 'reconnecting':
        return (
          <button
            onClick={onOpenWsLogs}
            className={`flex items-center gap-2 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors cursor-pointer ${
              darkMode
                ? 'bg-slate-900 text-amber-300 border-slate-800 hover:bg-slate-800'
                : 'bg-slate-800 text-amber-300 border-slate-700 hover:bg-slate-700/80'
            }`}
            title="WebSocket Reconnecting"
          >
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span>{t.reconnecting}</span>
          </button>
        );
      default:
        return (
          <button
            onClick={onOpenWsLogs}
            className={`flex items-center gap-2 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors cursor-pointer ${
              darkMode
                ? 'bg-slate-900 text-slate-400 border-slate-800 hover:bg-slate-800'
                : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700/80'
            }`}
            title="WebSocket Offline (Click to configure)"
          >
            <span className="w-2 h-2 rounded-full bg-slate-500" />
            <span>{t.offline}</span>
          </button>
        );
    }
  };

  return (
    <header className={`h-14 border-b sticky top-0 z-40 transition-colors ${
      darkMode 
        ? 'bg-[#090d16] text-white border-slate-850' 
        : 'bg-[#0f172a] text-white border-slate-800'
    }`}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-full flex items-center justify-between gap-4">
        {/* Left: Brand & Product Info */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm tracking-tight text-white">
              Sauda AI
            </span>
            <span className="bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[11px] px-2 py-0.5 rounded font-mono font-medium">
              {t.brandSubtitle}
            </span>
          </div>

          <div className="h-4 w-px bg-slate-800 hidden sm:block" />

          {/* WebSocket Status Indicator */}
          <div className="hidden sm:flex items-center">
            {renderWsIndicator()}
          </div>
        </div>

        {/* Right: Actions, Lang, and Theme Toggle */}
        <div className="flex items-center gap-2">
          {/* Dark / Light Mode Toggle Button */}
          <button
            onClick={onToggleDarkMode}
            className={`p-1.5 rounded-md border transition-colors cursor-pointer ${
              darkMode
                ? 'bg-slate-900 border-slate-800 text-amber-400 hover:bg-slate-800 hover:text-amber-300'
                : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white'
            }`}
            title={darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {darkMode ? (
              <Sun className="size-3.5" strokeWidth={1.5} />
            ) : (
              <Moon className="size-3.5" strokeWidth={1.5} />
            )}
          </button>

          {/* Language Switcher: EN / हिन्दी */}
          <div className={`flex items-center p-0.5 border rounded-md ${
            darkMode ? 'bg-slate-900 border-slate-800' : 'bg-slate-800/90 border-slate-700'
          }`}>
            <button
              onClick={() => onToggleLang('en')}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors cursor-pointer ${
                lang === 'en'
                  ? 'bg-amber-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Switch to English"
            >
              EN
            </button>
            <button
              onClick={() => onToggleLang('hi')}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors cursor-pointer ${
                lang === 'hi'
                  ? 'bg-amber-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="हिन्दी में बदलें"
            >
              हिन्दी
            </button>
          </div>

          {/* View Switcher: Table vs Status */}
          <div className={`flex items-center p-0.5 border rounded-md ${
            darkMode ? 'bg-slate-900 border-slate-800' : 'bg-slate-800/90 border-slate-700'
          }`}>
            <button
              onClick={() => onViewChange('table')}
              className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors cursor-pointer ${
                activeView === 'table'
                  ? darkMode ? 'bg-slate-800 text-white shadow-xs' : 'bg-slate-700 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.table}
            </button>
            <button
              onClick={() => onViewChange('kanban')}
              className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors cursor-pointer ${
                activeView === 'kanban'
                  ? darkMode ? 'bg-slate-800 text-white shadow-xs' : 'bg-slate-700 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.status}
            </button>
          </div>

          {/* Voice Simulator Panel Trigger */}
          <button
            onClick={onOpenVoiceSimulator}
            className={`px-2.5 py-1 rounded-md border transition-colors cursor-pointer flex items-center gap-1.5 text-xs font-medium ${
              darkMode 
                ? 'border-slate-800 hover:bg-slate-900 text-slate-200' 
                : 'border-slate-700 hover:bg-slate-800 text-slate-200'
            }`}
            title={t.voiceEngine}
          >
            <Mic className="size-3.5 text-amber-400" strokeWidth={1.5} />
            <span className="hidden md:inline">{t.voiceEngine}</span>
          </button>

          {/* Clear Data Button */}
          {shipmentsCount > 0 && (
            <button
              onClick={onClearAllData}
              className={`p-1.5 rounded-md border transition-colors cursor-pointer ${
                darkMode
                  ? 'border-slate-800 hover:bg-rose-950/60 hover:border-rose-900 text-slate-400 hover:text-rose-300'
                  : 'border-slate-700 hover:bg-rose-950/50 hover:border-rose-700/60 text-slate-400 hover:text-rose-300'
              }`}
              title={t.clearAll}
            >
              <Trash2 className="size-3.5" strokeWidth={1.5} />
            </button>
          )}

          {/* WebSocket Monitor / Logs */}
          <button
            onClick={onOpenWsLogs}
            className={`p-1.5 rounded-md border transition-colors cursor-pointer ${
              darkMode
                ? 'border-slate-800 hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                : 'border-slate-700 hover:bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
            title={t.wsMonitor}
          >
            <Terminal className="size-3.5" strokeWidth={1.5} />
          </button>

          {/* High-contrast amber/copper Simulate Button */}
          <button
            onClick={onQuickSimulate}
            className="px-3 py-1.5 rounded-md bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 shadow-xs"
          >
            <Sparkles className="size-3.5" strokeWidth={1.5} />
            <span>{t.simulateVoiceNote}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
