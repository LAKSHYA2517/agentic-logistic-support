import React, { useState } from 'react';
import { 
  X, 
  Truck, 
  MapPin, 
  IndianRupee, 
  Clock, 
  Mic, 
  Copy, 
  Check 
} from 'lucide-react';
import { STATUS_CONFIG } from '../utils/constants';
import { formatCurrencyINR, formatRelativeTime } from '../utils/formatters';
import { TRANSLATIONS } from '../utils/i18n';

export function ShipmentDetailsModal({
  shipment,
  isOpen,
  onClose,
  onStatusChange,
  lang = 'en',
  darkMode = false,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const [copied, setCopied] = useState(false);

  if (!isOpen || !shipment) return null;

  const totalValue = (Number(shipment.advance_paid) || 0) + (Number(shipment.balance_due) || 0);

  const handleCopy = () => {
    navigator.clipboard.writeText(shipment.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const statusConfig = STATUS_CONFIG[shipment.status] || {
    label: shipment.status,
    badgeClass: 'bg-slate-100 text-slate-700',
    darkBadgeClass: 'bg-slate-800 text-slate-300',
  };
  const badgeStyle = darkMode ? (statusConfig.darkBadgeClass || statusConfig.badgeClass) : statusConfig.badgeClass;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className={`w-full max-w-lg border rounded-lg shadow-xl overflow-hidden text-xs transition-colors ${
        darkMode ? 'bg-[#111827] border-slate-800 text-slate-100' : 'bg-white border-slate-300 text-slate-900'
      }`}>
        {/* Header */}
        <div className={`p-4 flex items-center justify-between ${
          darkMode ? 'bg-[#090d16] text-white border-b border-slate-800' : 'bg-slate-900 text-white'
        }`}>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-bold text-amber-300 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
              {shipment.id}
            </span>
            <button
              onClick={handleCopy}
              className="p-1 text-slate-400 hover:text-white rounded transition-colors cursor-pointer"
              title="Copy ID"
            >
              {copied ? <Check className="size-3 text-emerald-400" /> : <Copy className="size-3" />}
            </button>
            <span className="text-[11px] text-slate-400 ml-1">
              {formatRelativeTime(shipment.updated_at)}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white rounded-md hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Party & Route */}
          <div>
            <span className={`text-[10px] font-bold uppercase tracking-wider block mb-0.5 ${
              darkMode ? 'text-slate-400' : 'text-slate-500'
            }`}>
              {t.consigneeRoute}
            </span>
            <div className={`text-sm font-bold ${darkMode ? 'text-white' : 'text-slate-900'}`}>
              {shipment.party_name}
            </div>
            {(shipment.origin || shipment.destination) && (
              <div className={`flex items-center gap-1 text-xs mt-1 font-medium ${
                darkMode ? 'text-slate-400' : 'text-slate-600'
              }`}>
                <MapPin className="size-3 text-amber-500" strokeWidth={1.5} />
                <span>{shipment.origin || 'N/A'} → {shipment.destination || 'N/A'}</span>
              </div>
            )}
          </div>

          {/* Grid Info */}
          <div className="grid grid-cols-2 gap-3">
            <div className={`p-3 rounded-md border ${
              darkMode ? 'bg-[#0f172a] border-slate-800' : 'bg-slate-50 border-slate-200'
            }`}>
              <span className={`text-[10px] uppercase font-semibold tracking-wider block mb-1 ${
                darkMode ? 'text-slate-400' : 'text-slate-500'
              }`}>{t.truckPlate}</span>
              <span className={`font-mono text-xs font-bold ${darkMode ? 'text-slate-200' : 'text-slate-900'}`}>{shipment.truck_number}</span>
            </div>
            <div className={`p-3 rounded-md border ${
              darkMode ? 'bg-[#0f172a] border-slate-800' : 'bg-slate-50 border-slate-200'
            }`}>
              <span className={`text-[10px] uppercase font-semibold tracking-wider block mb-1 ${
                darkMode ? 'text-slate-400' : 'text-slate-500'
              }`}>{t.liveStatus}</span>
              <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${badgeStyle}`}>
                {t[shipment.status] || statusConfig.label || shipment.status}
              </span>
            </div>
          </div>

          {/* Financial Breakdown */}
          <div className={`p-3.5 rounded-md border ${
            darkMode ? 'bg-[#0f172a] border-slate-800' : 'bg-slate-50 border-slate-200'
          }`}>
            <span className={`text-[10px] uppercase tracking-wider font-bold block mb-2 ${
              darkMode ? 'text-slate-400' : 'text-slate-500'
            }`}>
              {t.financialBreakdown}
            </span>
            <div className="grid grid-cols-3 gap-2 font-mono text-center">
              <div>
                <span className="text-[10px] text-slate-500 block font-sans">{t.totalFreight}</span>
                <span className={`font-bold ${darkMode ? 'text-white' : 'text-slate-900'}`}>{formatCurrencyINR(totalValue)}</span>
              </div>
              <div className={`border-x ${darkMode ? 'border-slate-800' : 'border-slate-200'}`}>
                <span className="text-[10px] text-slate-500 block font-sans">{t.advance}</span>
                <span className={`font-bold ${darkMode ? 'text-emerald-400' : 'text-slate-900'}`}>{formatCurrencyINR(shipment.advance_paid)}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 block font-sans">{t.balance}</span>
                <span className={`font-bold ${darkMode ? 'text-amber-400' : 'text-slate-700'}`}>{formatCurrencyINR(shipment.balance_due)}</span>
              </div>
            </div>
          </div>

          {/* Source Voice Note Transcript */}
          {shipment.source_voice_note && (
            <div className={`p-3 rounded-md border ${
              darkMode ? 'bg-amber-950/30 border-amber-900/50 text-amber-200' : 'bg-amber-50/50 border-amber-200 text-slate-800'
            }`}>
              <div className={`flex items-center gap-1.5 text-xs font-bold mb-1 ${
                darkMode ? 'text-amber-400' : 'text-amber-900'
              }`}>
                <Mic className="size-3 text-amber-500" strokeWidth={1.5} />
                <span>{t.extractedTranscript}</span>
              </div>
              <p className="text-xs leading-relaxed italic">
                "{shipment.source_voice_note}"
              </p>
            </div>
          )}

          {/* Quick Status Shift */}
          {onStatusChange && (
            <div className={`pt-2 border-t ${darkMode ? 'border-slate-800' : 'border-slate-200'}`}>
              <span className="text-[11px] font-semibold text-slate-500 block mb-1.5 uppercase tracking-wider">{t.updateStatus}:</span>
              <div className="flex gap-1.5 flex-wrap">
                {['PENDING_LOADING', 'IN_TRANSIT', 'DELAYED', 'DELIVERED'].map((st) => (
                  <button
                    key={st}
                    onClick={() => {
                      onStatusChange(shipment.id, st);
                      onClose();
                    }}
                    className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors cursor-pointer border ${
                      shipment.status === st
                        ? 'bg-amber-600 text-white border-amber-600'
                        : darkMode ? 'bg-[#0f172a] border-slate-700 text-slate-200 hover:bg-slate-800' : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    {t[st] || STATUS_CONFIG[st]?.label || st}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
