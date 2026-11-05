import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { Loading } from "./components/ui";
import { useAuth } from "./hooks/useAuth";
import { AppLayout } from "./layouts/AppLayout";
import { LoginPage, RegisterPage } from "./pages/AuthPages";

// Pages are code-split so the login screen loads without the chart library.
const ExecutivePage = lazy(() => import("./pages/ExecutivePage"));
const SalesPage = lazy(() => import("./pages/SalesPage"));
const ForecastPage = lazy(() => import("./pages/ForecastPage"));
const AnomaliesPage = lazy(() => import("./pages/AnomaliesPage"));
const SegmentsPage = lazy(() => import("./pages/SegmentsPage"));
const CustomersPage = lazy(() => import("./pages/CustomersPage"));
const CustomerDetailPage = lazy(() => import("./pages/CustomerDetailPage"));
const ChurnPage = lazy(() => import("./pages/ChurnPage"));
const ClvPage = lazy(() => import("./pages/ClvPage"));
const RecommendationsPage = lazy(() => import("./pages/RecommendationsPage"));
const AssistantPage = lazy(() => import("./pages/AssistantPage"));
const ModelsPage = lazy(() => import("./pages/ModelsPage"));
const DataQualityPage = lazy(() => import("./pages/DataQualityPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <div className="p-8"><Loading label="Restoring session…" /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        {[
          ["/", <ExecutivePage />], ["/sales", <SalesPage />], ["/forecast", <ForecastPage />],
          ["/anomalies", <AnomaliesPage />], ["/segments", <SegmentsPage />], ["/customers", <CustomersPage />],
          ["/customers/:customerId", <CustomerDetailPage />], ["/churn", <ChurnPage />], ["/clv", <ClvPage />],
          ["/recommendations", <RecommendationsPage />], ["/assistant", <AssistantPage />],
          ["/models", <ModelsPage />], ["/data-quality", <DataQualityPage />], ["/settings", <SettingsPage />],
        ].map(([path, element]) => (
          <Route key={path as string} path={path as string}
            element={<Suspense fallback={<Loading />}>{element}</Suspense>} />
        ))}
        <Route path="*" element={<p className="text-sm text-text-2">Page not found.</p>} />
      </Route>
    </Routes>
  );
}
