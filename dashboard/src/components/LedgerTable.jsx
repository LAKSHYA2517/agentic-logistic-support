import { useMemo, useState } from 'react';
import { MapPin, Search, Truck } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { SHIPMENT_STATUSES } from '../utils/constants';
import { formatCurrencyINR, formatPhoneNumber } from '../utils/formatters';
import { getTranslations } from '../utils/i18n';

function valueOrDash(value) {
  return value || '—';
}

export function LedgerTable({
  shipments = [],
  isLoading = false,
  onSelectShipment,
  lang = 'en',
}) {
  const t = getTranslations(lang);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const filteredShipments = useMemo(() => {
    const query = searchTerm.trim().toLocaleLowerCase();
    return shipments.filter((shipment) => {
      const searchable = [
        shipment.id,
        shipment.party_name,
        shipment.driver_name,
        shipment.driver_phone,
        shipment.truck_number,
        shipment.destination,
      ]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase();
      const matchesSearch = !query || searchable.includes(query);
      const matchesStatus = statusFilter === 'ALL' || shipment.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [searchTerm, shipments, statusFilter]);

  const emptyTitle = shipments.length ? t.noMatchesTitle : t.noShipmentsTitle;
  const emptySubtitle = shipments.length ? t.noMatchesSubtitle : t.noShipmentsSubtitle;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-md">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder={t.searchPlaceholder}
            className="h-10 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-amber-500 focus:ring-2 focus:ring-amber-500/15"
          />
        </div>

        <div className="flex items-center gap-2 overflow-x-auto pb-1 lg:pb-0">
          {['ALL', ...SHIPMENT_STATUSES].map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => setStatusFilter(status)}
              className={`whitespace-nowrap rounded-lg border px-3 py-2 text-xs font-semibold transition-colors ${
                statusFilter === status
                  ? 'border-amber-600 bg-amber-50 text-amber-800'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              {status === 'ALL' ? t.filterAll : t.statuses[status]}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="grid min-h-28 place-items-center text-sm text-slate-500">{t.apiLoading}</div>
      ) : filteredShipments.length === 0 ? (
        <div className="grid min-h-40 place-items-center px-5 text-center">
          <div>
            <span className="mx-auto grid size-11 place-items-center rounded-full bg-slate-100 text-slate-500">
              <Truck className="size-5" />
            </span>
            <p className="mt-3 text-sm font-semibold text-slate-900">{emptyTitle}</p>
            <p className="mt-1 text-xs text-slate-500">{emptySubtitle}</p>
          </div>
        </div>
      ) : (
        <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full min-w-[1120px] border-collapse text-left">
              <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">{t.party}</th>
                  <th className="px-4 py-3">{t.driver}</th>
                  <th className="px-4 py-3">{t.truck}</th>
                  <th className="px-4 py-3">{t.destination}</th>
                  <th className="px-4 py-3 text-right">{t.advance}</th>
                  <th className="px-4 py-3 text-right">{t.remainingBalance}</th>
                  <th className="px-4 py-3">{t.status}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredShipments.map((shipment) => (
                  <tr
                    key={shipment.id}
                    onClick={() => onSelectShipment?.(shipment)}
                    className="cursor-pointer text-sm hover:bg-slate-50"
                  >
                    <td className="px-4 py-4">
                      <p className="font-semibold text-slate-950">
                        {valueOrDash(shipment.party_name)}
                      </p>
                      <p className="mt-0.5 text-[11px] font-medium text-slate-400">{shipment.id}</p>
                    </td>
                    <td className="px-4 py-4">
                      <p className="font-medium text-slate-800">
                        {valueOrDash(shipment.driver_name)}
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {shipment.driver_phone ? formatPhoneNumber(shipment.driver_phone) : t.unassigned}
                      </p>
                    </td>
                    <td className="px-4 py-4">
                      <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-xs font-bold text-slate-700">
                        {valueOrDash(shipment.truck_number)}
                      </span>
                    </td>
                    <td className="px-4 py-4 text-slate-700">
                      <span className="flex items-center gap-1.5">
                        <MapPin className="size-3.5 shrink-0 text-slate-400" />
                        {valueOrDash(shipment.destination)}
                      </span>
                    </td>
                    <td className="px-4 py-4 text-right font-medium text-slate-800">
                      {formatCurrencyINR(shipment.advance_paid, lang)}
                    </td>
                    <td className="px-4 py-4 text-right font-medium text-slate-800">
                      {formatCurrencyINR(shipment.balance_due, lang)}
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={shipment.status} lang={lang} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-slate-100 lg:hidden">
            {filteredShipments.map((shipment) => (
              <button
                key={shipment.id}
                type="button"
                onClick={() => onSelectShipment?.(shipment)}
                className="w-full p-4 text-left hover:bg-slate-50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-950">
                      {valueOrDash(shipment.party_name)}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-400">{shipment.id}</p>
                  </div>
                  <StatusBadge status={shipment.status} lang={lang} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                  <div>
                    <p className="text-slate-400">{t.driver}</p>
                    <p className="mt-0.5 font-medium text-slate-700">
                      {valueOrDash(shipment.driver_name)}
                    </p>
                    <p className="text-slate-500">
                      {shipment.driver_phone ? formatPhoneNumber(shipment.driver_phone) : t.unassigned}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-400">{t.truck}</p>
                    <p className="mt-0.5 font-mono font-bold text-slate-700">
                      {valueOrDash(shipment.truck_number)}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-400">{t.destination}</p>
                    <p className="mt-0.5 font-medium text-slate-700">
                      {valueOrDash(shipment.destination)}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-400">{t.remainingBalance}</p>
                    <p className="mt-0.5 font-medium text-slate-700">
                      {formatCurrencyINR(shipment.balance_due, lang)}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="border-t border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500">
        {t.showing(filteredShipments.length, shipments.length)}
      </div>
    </div>
  );
}
