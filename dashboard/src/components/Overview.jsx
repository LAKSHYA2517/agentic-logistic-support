import { Activity, MapPin, PackageCheck } from 'lucide-react';
import { MetricsCards } from './MetricsCards';
import { StatusBadge } from './StatusBadge';
import { formatDateTime } from '../utils/formatters';
import { getTranslations } from '../utils/i18n';

const ACTIVE_STATUSES = new Set(['ASSIGNED', 'IN_TRANSIT', 'NEEDS_REVIEW', 'PROCESSING']);

export function Overview({ shipments = [], drivers = [], isLoading = false, lang = 'en' }) {
  const t = getTranslations(lang);
  const activeShipments = shipments
    .filter((shipment) => ACTIVE_STATUSES.has(shipment.status))
    .slice(0, 5);
  const recentShipments = [...shipments]
    .sort((left, right) => new Date(right.updated_at || 0) - new Date(left.updated_at || 0))
    .slice(0, 6);

  return (
    <div className="space-y-6">
      <MetricsCards
        shipments={shipments}
        drivers={drivers}
        isLoading={isLoading}
        lang={lang}
      />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">{t.activeShipmentSummary}</h2>
              <p className="mt-0.5 text-xs text-slate-500">{t.activeShipmentSummarySubtitle}</p>
            </div>
            <PackageCheck className="size-5 text-amber-600" />
          </div>
          {isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">{t.apiLoading}</p>
          ) : activeShipments.length === 0 ? (
            <div className="px-5 py-8 text-center">
              <p className="text-sm font-semibold text-slate-700">{t.noActiveShipments}</p>
              <p className="mt-1 text-xs text-slate-500">{t.noActiveShipmentsSubtitle}</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {activeShipments.map((shipment) => (
                <div key={shipment.id} className="flex items-center justify-between gap-4 px-5 py-3.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">
                      {shipment.party_name || shipment.id}
                    </p>
                    <p className="mt-1 flex items-center gap-1 text-xs text-slate-500">
                      <MapPin className="size-3 shrink-0" />
                      <span className="truncate">
                        {shipment.destination || t.notAvailable} • {shipment.driver_name || t.unassigned}
                      </span>
                    </p>
                  </div>
                  <StatusBadge status={shipment.status} lang={lang} />
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">{t.recentActivity}</h2>
              <p className="mt-0.5 text-xs text-slate-500">{t.recentActivitySubtitle}</p>
            </div>
            <Activity className="size-5 text-blue-600" />
          </div>
          {isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">{t.apiLoading}</p>
          ) : recentShipments.length === 0 ? (
            <div className="px-5 py-8 text-center">
              <p className="text-sm font-semibold text-slate-700">{t.noRecentActivity}</p>
              <p className="mt-1 text-xs text-slate-500">{t.noRecentActivitySubtitle}</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {recentShipments.map((shipment) => (
                <div key={shipment.id} className="flex items-center gap-3 px-5 py-3.5">
                  <span className="size-2 shrink-0 rounded-full bg-amber-500" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800">
                      {shipment.party_name || shipment.id}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {t.statuses[shipment.status] || shipment.status}
                    </p>
                  </div>
                  <time className="shrink-0 text-[11px] text-slate-400">
                    {formatDateTime(shipment.updated_at, lang)}
                  </time>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
