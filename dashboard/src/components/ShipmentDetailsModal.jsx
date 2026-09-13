import { IndianRupee, MapPin, Phone, Truck, UserRound, X } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { formatCurrencyINR, formatDateTime, formatPhoneNumber } from '../utils/formatters';
import { getTranslations } from '../utils/i18n';

function Detail({ label, children }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <div className="mt-1 text-sm font-medium text-slate-800">{children || '—'}</div>
    </div>
  );
}

export function ShipmentDetailsModal({
  shipment,
  isOpen,
  onClose,
  lang = 'en',
}) {
  const t = getTranslations(lang);
  if (!isOpen || !shipment) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="shipment-details-title"
        onMouseDown={(event) => event.stopPropagation()}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <p className="text-xs font-semibold text-amber-700">{shipment.id}</p>
            <h2 id="shipment-details-title" className="mt-1 text-xl font-bold text-slate-950">
              {t.shipmentDetails}
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={shipment.status} lang={lang} />
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              aria-label={t.close}
            >
              <X className="size-4" />
            </button>
          </div>
        </div>

        <div className="space-y-6 p-5">
          <section>
            <h3 className="mb-3 text-sm font-bold text-slate-950">{t.routeAndParty}</h3>
            <div className="grid grid-cols-1 gap-4 rounded-xl bg-slate-50 p-4 sm:grid-cols-2">
              <Detail label={t.party}>
                <span className="flex items-center gap-2"><UserRound className="size-4 text-slate-400" />{shipment.party_name || '—'}</span>
              </Detail>
              <Detail label={t.destination}>
                <span className="flex items-center gap-2"><MapPin className="size-4 text-slate-400" />{shipment.destination || '—'}</span>
              </Detail>
              <Detail label={t.truck}>
                <span className="flex items-center gap-2 font-mono"><Truck className="size-4 text-slate-400" />{shipment.truck_number || '—'}</span>
              </Detail>
              <Detail label={t.lastUpdated}>{formatDateTime(shipment.updated_at, lang)}</Detail>
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-bold text-slate-950">{t.driverDetails}</h3>
            <div className="grid grid-cols-1 gap-4 rounded-xl border border-slate-200 p-4 sm:grid-cols-3">
              <Detail label={t.driver}>{shipment.driver_name || t.unassigned}</Detail>
              <Detail label={t.phone}>
                <span className="flex items-center gap-2"><Phone className="size-4 text-slate-400" />{shipment.driver_phone ? formatPhoneNumber(shipment.driver_phone) : '—'}</span>
              </Detail>
              <Detail label={t.confirmation}>
                {shipment.driver_confirmation_status
                  ? t.statuses[shipment.driver_confirmation_status] || shipment.driver_confirmation_status
                  : '—'}
              </Detail>
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-bold text-slate-950">{t.paymentDetails}</h3>
            <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-200 p-4">
              <Detail label={t.advance}>
                <span className="flex items-center gap-1"><IndianRupee className="size-4 text-emerald-600" />{formatCurrencyINR(shipment.advance_paid, lang).replace('₹', '').trim()}</span>
              </Detail>
              <Detail label={t.remainingBalance}>
                <span className="flex items-center gap-1"><IndianRupee className="size-4 text-amber-600" />{formatCurrencyINR(shipment.balance_due, lang).replace('₹', '').trim()}</span>
              </Detail>
            </div>
          </section>

          {shipment.source_voice_note && (
            <section>
              <h3 className="mb-3 text-sm font-bold text-slate-950">{t.sourceTranscript}</h3>
              <p className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">
                {shipment.source_voice_note}
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
