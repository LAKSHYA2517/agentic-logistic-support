import { useCallback, useEffect, useState } from 'react';
import { Dashboard } from './components/Dashboard';

const DASHBOARD_POLL_INTERVAL_MS = 5000;

function App() {
  const [shipments, setShipments] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [apiStatus, setApiStatus] = useState('loading');
  const [loadError, setLoadError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [lang, setLang] = useState(() => localStorage.getItem('sauda_lang') || 'en');

  const loadDashboardData = useCallback(async () => {
    try {
      const [shipmentsResponse, driversResponse] = await Promise.all([
        fetch('/api/shipments', { cache: 'no-store' }),
        fetch('/api/drivers', { cache: 'no-store' }),
      ]);
      if (!shipmentsResponse.ok || !driversResponse.ok) {
        throw new Error('Dashboard API returned an unsuccessful response.');
      }

      const [shipmentData, driverData] = await Promise.all([
        shipmentsResponse.json(),
        driversResponse.json(),
      ]);
      if (!Array.isArray(shipmentData) || !Array.isArray(driverData)) {
        throw new Error('Dashboard API returned an unexpected response.');
      }

      setShipments(shipmentData);
      setDrivers(driverData);
      setApiStatus('online');
      setLoadError(null);
      setLastUpdated(new Date());
    } catch (error) {
      setApiStatus('offline');
      setLoadError(error instanceof Error ? error.message : 'Unable to load dashboard data.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Old simulator versions persisted fake shipments here. The live dashboard
    // is API-only, so remove that stale browser data once and never read it.
    localStorage.removeItem('sauda_shipments');
    localStorage.removeItem('sauda_theme');
    const initialLoadId = window.setTimeout(loadDashboardData, 0);
    const intervalId = window.setInterval(loadDashboardData, DASHBOARD_POLL_INTERVAL_MS);
    return () => {
      window.clearTimeout(initialLoadId);
      window.clearInterval(intervalId);
    };
  }, [loadDashboardData]);

  const handleLanguageChange = useCallback((language) => {
    setLang(language);
    localStorage.setItem('sauda_lang', language);
  }, []);

  return (
    <Dashboard
      shipments={shipments}
      drivers={drivers}
      isLoading={isLoading}
      apiStatus={apiStatus}
      loadError={loadError}
      lastUpdated={lastUpdated}
      onRetry={loadDashboardData}
      lang={lang}
      setLang={handleLanguageChange}
    />
  );
}

export default App;
