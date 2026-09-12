import React from 'react';
import { Truck, IndianRupee, Clock } from 'lucide-react';
import { formatCurrencyINR } from '../utils/formatters';
import { TRANSLATIONS } from '../utils/i18n';

export function MetricsCards({ shipments = [], lang = 'en', darkMode = false }) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  const totalShipments = shipments.length;
  const inTransitCount = shipments.filter((s) => s.status === 'IN_TRANSIT').length;
  const delayedCount = shipments.filter((s) => s.status === 'DELAYED').length;

  const totalAdvance = shipments.reduce((sum, item) => sum + (Number(item.advance_paid) || 0), 0);
  const totalBalance = shipments.reduce((sum, item) => sum + (Number(item.balance_due) || 0), 0);

  const cards = [
    {
      title: t.activeShipments,
      value: totalShipments,
      subtext: t.activeShipmentsSub(inTransitCount, delayedCount),
      icon: Truck,
      borderTopClass: 'border-t-2 border-t-blue-500',
      isCurrency: false,
    },
    {
      title: t.totalAdvance,
      value: formatCurrencyINR(totalAdvance),
      subtext: t.totalAdvanceSub,
      icon: IndianRupee,
      borderTopClass: 'border-t-2 border-t-emerald-500',
      isCurrency: true,
    },
    {
      title: t.outstandingBalance,
      value: formatCurrencyINR(totalBalance),
      subtext: t.outstandingBalanceSub,
      icon: Clock,
      borderTopClass: 'border-t-2 border-t-amber-500',
      isCurrency: true,
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
      {cards.map((card, idx) => {
        const Icon = card.icon;
        return (
          <div
            key={idx}
            className={`rounded-lg border shadow-xs p-4 transition-all ${card.borderTopClass} ${
              darkMode 
                ? 'bg-[#111827] border-slate-800 text-slate-100' 
                : 'bg-white border-slate-200/80 text-slate-900'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className={`text-xs font-semibold tracking-wider uppercase ${
                darkMode ? 'text-slate-400' : 'text-slate-500'
              }`}>
                {card.title}
              </span>
              <Icon className={`size-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`} strokeWidth={1.5} />
            </div>

            <div className={`font-bold text-2xl font-mono tracking-tight ${
              darkMode ? 'text-white' : 'text-slate-900'
            }`}>
              {card.value}
            </div>

            <p className={`mt-1.5 text-xs truncate font-normal ${
              darkMode ? 'text-slate-400' : 'text-slate-500'
            }`}>
              {card.subtext}
            </p>
          </div>
        );
      })}
    </div>
  );
}
