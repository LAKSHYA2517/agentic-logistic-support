import { useState } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { DriversSection } from './DriversSection';
import { Header } from './Header';
import { LedgerTable } from './LedgerTable';
import { Overview } from './Overview';
import { ShipmentDetailsModal } from './ShipmentDetailsModal';
import { getTranslations } from '../utils/i18n';
import { formatDateTime } from '../utils/formatters';

export function Dashboard({
  shipments = [],
  drivers = [],
  isLoading = false,
  apiStatus = 'loading',
  loadError,
  lastUpdated,
  onRetry,
  lang = 'en',
  setLang,
}) {
  const t = getTranslations(lang);
  const [activeSection, setActiveSection] = useState('overview');
  const [selectedShipment, setSelectedShipment] = useState(null);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950 antialiased">
      <Header
        activeSection={activeSection}
        onNavigate={setActiveSection}
        apiStatus={apiStatus}
        lang={lang}
        onLanguageChange={setLang}
      />

      <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <div className="mb-6 flex flex-col justify-between gap-2 sm:flex-row sm:items-end">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">
              {t.pageEyebrow}
            </p>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {activeSection === 'overview'
                ? t.pageTitle
                : activeSection === 'shipments'
                  ? t.shipmentsTitle
                  : t.driversTitle}
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              {activeSection === 'overview'
                ? t.pageSubtitle
                : activeSection === 'shipments'
                  ? t.shipmentsSubtitle
                  : t.driversSubtitle}
            </p>
          </div>
          <p className="text-xs text-slate-500">
            {t.lastUpdated}:{' '}
            <span className="font-medium text-slate-700">
              {lastUpdated ? formatDateTime(lastUpdated, lang) : t.notAvailable}
            </span>
          </p>
        </div>

        {loadError && (
          <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="size-4 shrink-0" />
              <span>{t.loadError}</span>
            </div>
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold hover:bg-rose-100"
            >
              <RefreshCw className="size-3.5" />
              {t.retry}
            </button>
          </div>
        )}

        {activeSection === 'overview' && (
          <Overview
            shipments={shipments}
            drivers={drivers}
            isLoading={isLoading}
            lang={lang}
          />
        )}

        {activeSection === 'shipments' && (
          <LedgerTable
            shipments={shipments}
            isLoading={isLoading}
            onSelectShipment={setSelectedShipment}
            lang={lang}
          />
        )}

        {activeSection === 'drivers' && (
          <DriversSection drivers={drivers} isLoading={isLoading} lang={lang} />
        )}
      </main>

      <footer className="mt-8 border-t border-slate-200 bg-white py-5 text-xs text-slate-500">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-1 px-4 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <span>{t.footerText}</span>
          <span>{t.footerSubtitle}</span>
        </div>
      </footer>

      <ShipmentDetailsModal
        shipment={selectedShipment}
        isOpen={Boolean(selectedShipment)}
        onClose={() => setSelectedShipment(null)}
        lang={lang}
      />
    </div>
  );
}
