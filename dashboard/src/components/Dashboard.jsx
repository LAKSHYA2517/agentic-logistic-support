import React, { useState } from 'react';
import { Header } from './Header';
import { MetricsCards } from './MetricsCards';
import { LedgerTable } from './LedgerTable';
import { KanbanBoard } from './KanbanBoard';
import { VoiceSimulatorDrawer } from './VoiceSimulatorDrawer';
import { WebSocketLogsModal } from './WebSocketLogsModal';
import { ShipmentDetailsModal } from './ShipmentDetailsModal';
import { generateDynamicVoicePayload } from '../utils/constants';
import { TRANSLATIONS } from '../utils/i18n';

export function Dashboard({
  shipments = [],
  highlightedIds = new Set(),
  wsStatus,
  wsUrl,
  onUpdateWsUrl,
  onConnect,
  onDisconnect,
  wsLogs = [],
  onClearWsLogs,
  onSimulateVoicePayload,
  onClearAllData,
  onStatusChange,
  lang = 'en',
  setLang,
  darkMode = false,
  setDarkMode,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const [activeView, setActiveView] = useState('table');
  const [isVoiceDrawerOpen, setIsVoiceDrawerOpen] = useState(false);
  const [isWsLogsModalOpen, setIsWsLogsModalOpen] = useState(false);
  const [selectedShipment, setSelectedShipment] = useState(null);

  const handleQuickSimulate = () => {
    const payload = generateDynamicVoicePayload();
    onSimulateVoicePayload(payload);
  };

  return (
    <div className={`min-h-screen flex flex-col antialiased transition-colors ${
      darkMode ? 'dark bg-[#080d1a] text-slate-100' : 'bg-[#f1f3f5] text-slate-900'
    }`}>
      {/* 56px Deep Slate Navigation Bar */}
      <Header
        wsStatus={wsStatus}
        activeView={activeView}
        onViewChange={setActiveView}
        onOpenVoiceSimulator={() => setIsVoiceDrawerOpen(true)}
        onOpenWsLogs={() => setIsWsLogsModalOpen(true)}
        onQuickSimulate={handleQuickSimulate}
        onClearAllData={onClearAllData}
        shipmentsCount={shipments.length}
        lang={lang}
        onToggleLang={setLang}
        darkMode={darkMode}
        onToggleDarkMode={() => setDarkMode((prev) => !prev)}
      />

      {/* Main Operations Canvas */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-5 space-y-4">
        {/* 3 Tactile Metric Cards with Top Accent Stripes */}
        <MetricsCards shipments={shipments} lang={lang} darkMode={darkMode} />

        {/* High-Density Ledger Table or Kanban View */}
        {activeView === 'table' ? (
          <LedgerTable
            shipments={shipments}
            highlightedIds={highlightedIds}
            onSelectShipment={setSelectedShipment}
            lang={lang}
            darkMode={darkMode}
          />
        ) : (
          <KanbanBoard
            shipments={shipments}
            highlightedIds={highlightedIds}
            onSelectShipment={setSelectedShipment}
            onStatusChange={onStatusChange}
            lang={lang}
            darkMode={darkMode}
          />
        )}
      </main>

      {/* Footer */}
      <footer className={`border-t py-3 mt-auto text-xs transition-colors ${
        darkMode ? 'border-slate-850 bg-[#090d16] text-slate-400' : 'border-slate-200 bg-white text-slate-500'
      }`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>{t.footerText}</span>
          <span className={`font-mono text-[11px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
            {t.footerProtocol}
          </span>
        </div>
      </footer>

      {/* Slide-over Drawer & Modals */}
      <VoiceSimulatorDrawer
        isOpen={isVoiceDrawerOpen}
        onClose={() => setIsVoiceDrawerOpen(false)}
        onSimulateVoiceNote={onSimulateVoicePayload}
        lang={lang}
        darkMode={darkMode}
      />

      <WebSocketLogsModal
        isOpen={isWsLogsModalOpen}
        onClose={() => setIsWsLogsModalOpen(false)}
        wsStatus={wsStatus}
        wsUrl={wsUrl}
        onUpdateWsUrl={onUpdateWsUrl}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
        logs={wsLogs}
        onClearLogs={onClearWsLogs}
        lang={lang}
        darkMode={darkMode}
      />

      <ShipmentDetailsModal
        shipment={selectedShipment}
        isOpen={!!selectedShipment}
        onClose={() => setSelectedShipment(null)}
        onStatusChange={onStatusChange}
        lang={lang}
        darkMode={darkMode}
      />
    </div>
  );
}
