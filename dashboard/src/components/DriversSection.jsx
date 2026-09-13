import { MapPin, Phone, Truck, Users } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { formatPhoneNumber } from '../utils/formatters';
import { getTranslations } from '../utils/i18n';

function initials(name) {
  return String(name || '?')
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase();
}

export function DriversSection({
  drivers = [],
  isLoading = false,
  lang = 'en',
}) {
  const t = getTranslations(lang);

  return (
    <div className="space-y-3">
      <p className="text-right text-xs font-medium text-slate-500">
        {t.registeredDrivers(drivers.length)}
      </p>

      {isLoading ? (
        <div className="grid min-h-28 place-items-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500">
          {t.apiLoading}
        </div>
      ) : drivers.length === 0 ? (
        <div className="grid min-h-36 place-items-center rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
          <div>
            <span className="mx-auto grid size-11 place-items-center rounded-full bg-slate-100 text-slate-500">
              <Users className="size-5" />
            </span>
            <p className="mt-3 text-sm font-semibold text-slate-900">{t.noDriversTitle}</p>
            <p className="mt-1 text-xs text-slate-500">{t.noDriversSubtitle}</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {drivers.map((driver) => (
            <article
              key={driver.id}
              className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-full bg-amber-100 text-xs font-bold text-amber-800">
                    {initials(driver.name)}
                  </span>
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-bold text-slate-950">
                      {driver.name}
                    </h3>
                    <a
                      href={`tel:+${String(driver.phone).replace(/\D/g, '')}`}
                      className="mt-0.5 flex items-center gap-1 text-xs text-slate-500 hover:text-amber-700"
                    >
                      <Phone className="size-3" />
                      {formatPhoneNumber(driver.phone)}
                    </a>
                  </div>
                </div>
                <StatusBadge status={driver.availability} lang={lang} />
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs">
                <div>
                  <p className="text-slate-400">{t.truck}</p>
                  <p className="mt-1 flex items-center gap-1.5 font-mono font-bold text-slate-800">
                    <Truck className="size-3.5 text-slate-400" />
                    {driver.truck_number}
                  </p>
                </div>
                <div>
                  <p className="text-slate-400">{t.status}</p>
                  <p className="mt-1 font-semibold text-slate-800">
                    {driver.current_status ? t.statuses[driver.current_status] : t.statuses.FREE}
                  </p>
                </div>
              </div>

              {driver.availability === 'OCCUPIED' && (
                <div className="mt-4 border-t border-slate-100 pt-4 text-xs">
                  <p className="font-semibold uppercase tracking-wide text-slate-400">{t.currentDelivery}</p>
                  <div className="mt-2 flex items-start gap-2">
                    <MapPin className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
                    <div>
                      <p className="font-semibold text-slate-800">
                        {driver.destination || t.notAvailable}
                      </p>
                      <p className="mt-0.5 text-slate-500">
                        {driver.party_name || t.notAvailable} • {driver.current_shipment_id}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
