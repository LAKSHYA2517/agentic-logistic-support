import { IndianRupee, Route, Truck, UserCheck } from 'lucide-react';
import { formatCurrencyINR } from '../utils/formatters';
import { getTranslations } from '../utils/i18n';

export function MetricsCards({
  shipments = [],
  drivers = [],
  isLoading = false,
  lang = 'en',
}) {
  const t = getTranslations(lang);
  const activeCount = shipments.filter((shipment) => shipment.status !== 'DELIVERED').length;
  const inTransitCount = shipments.filter((shipment) => shipment.status === 'IN_TRANSIT').length;
  const availableCount = drivers.filter((driver) => driver.availability === 'FREE').length;
  const openBalance = shipments
    .filter((shipment) => shipment.status !== 'DELIVERED')
    .reduce((sum, shipment) => sum + (Number(shipment.balance_due) || 0), 0);

  const cards = [
    {
      title: t.activeShipments,
      value: activeCount,
      subtext: t.activeShipmentsSub,
      icon: Route,
      iconClass: 'bg-blue-50 text-blue-700',
    },
    {
      title: t.inTransit,
      value: inTransitCount,
      subtext: t.inTransitSub,
      icon: Truck,
      iconClass: 'bg-violet-50 text-violet-700',
    },
    {
      title: t.availableDrivers,
      value: availableCount,
      subtext: t.availableDriversSub(drivers.length),
      icon: UserCheck,
      iconClass: 'bg-emerald-50 text-emerald-700',
    },
    {
      title: t.outstandingBalance,
      value: formatCurrencyINR(openBalance, lang),
      subtext: t.outstandingBalanceSub,
      icon: IndianRupee,
      iconClass: 'bg-amber-50 text-amber-700',
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ title, value, subtext, icon: Icon, iconClass }) => (
        <article
          key={title}
          className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {title}
              </p>
              <p className="mt-2 text-2xl font-bold tracking-tight text-slate-950">
                {isLoading ? '—' : value}
              </p>
            </div>
            <span className={`grid size-9 place-items-center rounded-lg ${iconClass}`}>
              <Icon className="size-4.5" strokeWidth={1.8} />
            </span>
          </div>
          <p className="mt-2 text-xs text-slate-500">{subtext}</p>
        </article>
      ))}
    </div>
  );
}
