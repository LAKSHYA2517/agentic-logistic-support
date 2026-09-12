import React, { useState, useEffect } from 'react';
import { 
  Sparkles, 
  Mic, 
  Send, 
  RefreshCw, 
  X
} from 'lucide-react';
import { generateDynamicVoicePayload, generateRandomIndianPlate } from '../utils/constants';
import { TRANSLATIONS } from '../utils/i18n';

export function VoiceSimulatorDrawer({
  isOpen,
  onClose,
  onSimulateVoiceNote,
  lang = 'en',
  darkMode = false,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const [isAutoStreaming, setIsAutoStreaming] = useState(false);
  const [streamInterval, setStreamInterval] = useState(4);
  const [isSimulatingAudio, setIsSimulatingAudio] = useState(false);

  // Custom editor state
  const [customParty, setCustomParty] = useState('Rajeshwari Transport Corp');
  const [customTruck, setCustomTruck] = useState(generateRandomIndianPlate());
  const [customAdvance, setCustomAdvance] = useState(18000);
  const [customBalance, setCustomBalance] = useState(32000);
  const [customStatus, setCustomStatus] = useState('IN_TRANSIT');
  const [customVoiceNote, setCustomVoiceNote] = useState('Truck loaded at warehouse. Advance ₹18,000 paid.');

  useEffect(() => {
    let intervalId = null;
    if (isAutoStreaming) {
      intervalId = setInterval(() => {
        triggerRandomSimulation();
      }, streamInterval * 1000);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [isAutoStreaming, streamInterval]);

  const triggerRandomSimulation = () => {
    const payload = generateDynamicVoicePayload();
    onSimulateVoiceNote(payload);
  };

  const handleSingleQuickSimulate = () => {
    setIsSimulatingAudio(true);
    setTimeout(() => {
      triggerRandomSimulation();
      setIsSimulatingAudio(false);
    }, 300);
  };

  const handleCustomDispatch = (e) => {
    e.preventDefault();
    const orderId = `SHP-${Math.floor(1000 + Math.random() * 9000)}`;
    const payload = {
      event: 'SHIPMENT_UPDATED',
      data: {
        id: orderId,
        party_name: customParty,
        truck_number: customTruck,
        advance_paid: Number(customAdvance) || 0,
        balance_due: Number(customBalance) || 0,
        status: customStatus,
        updated_at: new Date().toISOString(),
        source_voice_note: customVoiceNote,
      },
    };
    onSimulateVoiceNote(payload);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 transition-opacity">
      <div className={`w-full max-w-md h-full border-l p-6 flex flex-col justify-between overflow-y-auto shadow-2xl transition-colors ${
        darkMode ? 'bg-[#111827] border-slate-800 text-slate-100' : 'bg-white border-slate-300 text-slate-900'
      }`}>
        <div>
          {/* Header */}
          <div className={`flex items-center justify-between pb-4 border-b ${
            darkMode ? 'border-slate-800' : 'border-slate-200'
          }`}>
            <div>
              <h2 className={`text-sm font-bold uppercase tracking-wider ${darkMode ? 'text-white' : 'text-slate-900'}`}>{t.voiceSimulatorTitle}</h2>
              <p className={`text-xs ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>
                {t.voiceSimulatorSub}
              </p>
            </div>
            <button
              onClick={onClose}
              className={`p-1 rounded-md transition-colors cursor-pointer ${
                darkMode ? 'text-slate-400 hover:text-white hover:bg-slate-800' : 'text-slate-400 hover:text-slate-700 hover:bg-slate-100'
              }`}
            >
              <X className="size-4" strokeWidth={1.5} />
            </button>
          </div>

          {/* Quick Simulation */}
          <div className="my-5">
            <button
              onClick={handleSingleQuickSimulate}
              disabled={isSimulatingAudio}
              className="w-full py-2.5 px-3 rounded-md bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold transition-colors cursor-pointer flex items-center justify-center gap-2 disabled:opacity-50 shadow-xs"
            >
              {isSimulatingAudio ? (
                <>
                  <RefreshCw className="size-3.5 animate-spin" strokeWidth={1.5} />
                  <span>Processing...</span>
                </>
              ) : (
                <>
                  <Sparkles className="size-3.5" strokeWidth={1.5} />
                  <span>{t.pushSimulatedPayload}</span>
                </>
              )}
            </button>
          </div>

          {/* Continuous Auto-Stream Mode */}
          <div className={`p-3.5 rounded-md border mb-5 text-xs ${
            darkMode ? 'bg-[#0b0f19] border-slate-800' : 'bg-slate-50 border-slate-200'
          }`}>
            <div className="flex items-center justify-between mb-2">
              <span className={`font-semibold ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>{t.autoStreamInterval}</span>
              <button
                onClick={() => setIsAutoStreaming(!isAutoStreaming)}
                className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors cursor-pointer ${
                  isAutoStreaming
                    ? 'bg-rose-950/80 text-rose-300 border border-rose-800'
                    : darkMode ? 'bg-slate-800 text-slate-200 hover:bg-slate-700' : 'bg-slate-200 text-slate-800 hover:bg-slate-300'
                }`}
              >
                {isAutoStreaming ? t.stopStream : t.startStream}
              </button>
            </div>

            <div className={`flex items-center justify-between ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>
              <span>{t.everySeconds(streamInterval)}</span>
              <input
                type="range"
                min="2"
                max="10"
                value={streamInterval}
                onChange={(e) => setStreamInterval(Number(e.target.value))}
                className="w-28 accent-amber-600 cursor-pointer"
              />
            </div>
          </div>

          {/* Custom Shipment Builder */}
          <form onSubmit={handleCustomDispatch} className="space-y-3 text-xs">
            <div className={`text-xs font-bold uppercase tracking-wider pb-1 border-b ${
              darkMode ? 'text-slate-200 border-slate-800' : 'text-slate-800 border-slate-200'
            }`}>
              {t.customBuilder}
            </div>

            <div>
              <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.partyLabel}</label>
              <input
                type="text"
                value={customParty}
                onChange={(e) => setCustomParty(e.target.value)}
                className={`w-full px-2.5 py-1.5 rounded-md border outline-none ${
                  darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                }`}
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.truckNumber}</label>
                <input
                  type="text"
                  value={customTruck}
                  onChange={(e) => setCustomTruck(e.target.value)}
                  className={`w-full px-2.5 py-1.5 font-mono font-semibold rounded-md border outline-none ${
                    darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                  }`}
                  required
                />
              </div>
              <div>
                <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.statusCol}</label>
                <select
                  value={customStatus}
                  onChange={(e) => setCustomStatus(e.target.value)}
                  className={`w-full px-2.5 py-1.5 rounded-md border outline-none ${
                    darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                  }`}
                >
                  <option value="IN_TRANSIT">{t.IN_TRANSIT}</option>
                  <option value="PENDING_LOADING">{t.PENDING_LOADING}</option>
                  <option value="DELAYED">{t.DELAYED}</option>
                  <option value="DELIVERED">{t.DELIVERED}</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.advance} (₹)</label>
                <input
                  type="number"
                  value={customAdvance}
                  onChange={(e) => setCustomAdvance(e.target.value)}
                  className={`w-full px-2.5 py-1.5 font-mono font-semibold rounded-md border outline-none ${
                    darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                  }`}
                />
              </div>
              <div>
                <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.balance} (₹)</label>
                <input
                  type="number"
                  value={customBalance}
                  onChange={(e) => setCustomBalance(e.target.value)}
                  className={`w-full px-2.5 py-1.5 font-mono font-semibold rounded-md border outline-none ${
                    darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                  }`}
                />
              </div>
            </div>

            <div>
              <label className={`block font-medium mb-1 ${darkMode ? 'text-slate-300' : 'text-slate-700'}`}>{t.audioTranscriptLabel}</label>
              <textarea
                rows={2}
                value={customVoiceNote}
                onChange={(e) => setCustomVoiceNote(e.target.value)}
                className={`w-full px-2.5 py-1.5 rounded-md border outline-none resize-none ${
                  darkMode ? 'bg-[#131b2e] border-slate-700 text-white focus:border-slate-500' : 'bg-white border-slate-200 text-slate-900 focus:border-slate-400'
                }`}
              />
            </div>

            <button
              type="submit"
              className={`w-full py-2 px-3 rounded-md font-medium transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                darkMode ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-900 hover:bg-slate-800 text-white'
              }`}
            >
              <Send className="size-3.5" strokeWidth={1.5} />
              <span>{t.dispatchPayload}</span>
            </button>
          </form>
        </div>

        {/* Footer */}
        <div className={`pt-4 border-t text-[11px] flex items-center justify-between font-mono ${
          darkMode ? 'border-slate-800 text-slate-500' : 'border-slate-200 text-slate-400'
        }`}>
          <span>EVENT: SHIPMENT_UPDATED</span>
          <span>WebSocket Stream</span>
        </div>
      </div>
    </div>
  );
}
