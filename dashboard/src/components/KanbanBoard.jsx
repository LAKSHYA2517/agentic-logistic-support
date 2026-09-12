import React from 'react';
import { 
  Truck, 
  ArrowRight, 
  MapPin, 
  IndianRupee 
} from 'lucide-react';
import { STATUS_CONFIG } from '../utils/constants';
import { formatCurrencyINR, formatRelativeTime } from '../utils/formatters';
import { TRANSLATIONS } from '../utils/i18n';

const KANBAN_COLUMNS = [
  { key: 'PENDING_LOADING', borderTop: 'border-t-2 border-t-amber-500' },
  { key: 'IN_TRANSIT', borderTop: 'border-t-2 border-t-blue-500' },
  { key: 'DELAYED', borderTop: 'border-t-2 border-t-rose-500' },
  { key: 'DELIVERED', borderTop: 'border-t-2 border-t-emerald-500' },
];

export function KanbanBoard({
  shipments = [],
  highlightedIds = new Set(),
  onSelectShipment,
  onStatusChange,
  lang = 'en',
  darkMode = false,
}) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;

  const getNextStatus = (currentStatus) => {
    switch (currentStatus) {
      case 'PENDING_LOADING':
        return 'IN_TRANSIT';
      case 'IN_TRANSIT':
        return 'DELIVERED';
      case 'DELAYED':
        return 'IN_TRANSIT';
      default:
        return null;
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3.5">
      {KANBAN_COLUMNS.map((col) => {
        const columnShipments = shipments.filter((s) => s.status === col.key);
        const colTitle = t[col.key] || STATUS_CONFIG[col.key]?.label || col.key;

        return (
          <div
            key={col.key}
            className={`border shadow-xs rounded-lg p-3 flex flex-col min-h-[420px] transition-colors ${col.borderTop} ${
              darkMode ? 'bg-[#111827] border-slate-800' : 'bg-white border-slate-200'
            }`}
          >
            {/* Column Header */}
            <div className={`flex items-center justify-between pb-2 mb-2 border-b ${
              darkMode ? 'border-slate-800' : 'border-slate-200'
            }`}>
              <span className={`text-xs font-bold uppercase tracking-wider ${
                darkMode ? 'text-slate-300' : 'text-slate-700'
              }`}>
                {colTitle}
              </span>
              <span className={`text-[11px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                darkMode ? 'bg-slate-800 text-slate-300 border-slate-700' : 'bg-slate-100 text-slate-700 border-slate-200'
              }`}>
                {t.truckCount(columnShipments.length)}
              </span>
            </div>

            {/* Cards List */}
            <div className="flex-1 space-y-2.5 overflow-y-auto max-h-[calc(100vh-320px)]">
              {columnShipments.length === 0 ? (
                <div className={`text-center py-10 text-xs border border-dashed rounded-md ${
                  darkMode ? 'border-slate-800 text-slate-600' : 'border-slate-200 text-slate-400'
                }`}>
                  {t.noShipmentsInLane}
                </div>
              ) : (
                columnShipments.map((shipment) => {
                  const isHighlighted = highlightedIds.has(shipment.id);
                  const nextStatus = getNextStatus(shipment.status);
                  const nextLabel = nextStatus ? (t[nextStatus] || STATUS_CONFIG[nextStatus]?.label) : '';

                  return (
                    <div
                      key={shipment.id}
                      onClick={() => onSelectShipment && onSelectShipment(shipment)}
                      className={`p-3 border rounded-md transition-all cursor-pointer text-xs shadow-2xs ${
                        darkMode 
                          ? 'bg-[#0f172a] border-slate-800 hover:border-slate-700 hover:bg-[#131d35]' 
                          : 'bg-slate-50/60 border-slate-200 hover:border-slate-300 hover:bg-white'
                      } ${isHighlighted ? 'animate-amber-flash' : ''}`}
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <span className={`font-mono text-[11px] font-bold px-1.5 py-0.5 rounded border ${
                          darkMode ? 'bg-slate-800 text-slate-300 border-slate-700' : 'bg-slate-200/80 text-slate-800 border-slate-300'
                        }`}>
                          {shipment.id}
                        </span>
                        <span className="text-[10px] text-slate-400 font-medium">
                          {formatRelativeTime(shipment.updated_at)}
                        </span>
                      </div>

                      <div className={`font-bold truncate mb-1 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
                        {shipment.party_name}
                      </div>

                      <div className="flex items-center gap-1 font-mono text-[11px] text-slate-400 mb-2">
                        <Truck className="size-3 text-slate-500" strokeWidth={1.5} />
                        <span className="font-semibold">{shipment.truck_number}</span>
                      </div>

                      <div className={`pt-2 border-t flex items-center justify-between font-mono text-[11px] ${
                        darkMode ? 'border-slate-800' : 'border-slate-200'
                      }`}>
                        <div>
                          <span className="text-slate-400 text-[10px] block font-sans">{t.advance}</span>
                          <span className={`font-bold ${darkMode ? 'text-white' : 'text-slate-900'}`}>{formatCurrencyINR(shipment.advance_paid)}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-slate-400 text-[10px] block font-sans">{t.balance}</span>
                          <span className="font-bold text-slate-400">{formatCurrencyINR(shipment.balance_due)}</span>
                        </div>
                      </div>

                      {nextStatus && onStatusChange && (
                        <div className={`mt-2.5 pt-2 border-t flex justify-end ${
                          darkMode ? 'border-slate-800' : 'border-slate-200'
                        }`}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onStatusChange(shipment.id, nextStatus);
                            }}
                            className={`text-[11px] flex items-center gap-1 font-medium border px-2 py-0.5 rounded cursor-pointer transition-colors ${
                              darkMode
                                ? 'bg-slate-800 hover:bg-slate-750 border-slate-700 text-slate-200'
                                : 'bg-white hover:bg-slate-100 border-slate-200 text-slate-700 hover:text-slate-900'
                            }`}
                          >
                            <span>{t.moveTo}: {nextLabel}</span>
                            <ArrowRight className="size-3" strokeWidth={1.5} />
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
