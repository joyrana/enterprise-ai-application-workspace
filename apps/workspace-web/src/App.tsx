import { FluentProvider, webDarkTheme, webLightTheme } from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { CreateProjectProvider } from "./pages/CreateProjectProvider";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrganizationPage } from "./pages/OrganizationPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/project/ProjectPage";

function usePrefersDark(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setDark(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return dark;
}

export function AppRoutes() {
  return (
    <CreateProjectProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/projects/:projectId/:tab" element={<ProjectPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AppShell>
    </CreateProjectProvider>
  );
}

export function App() {
  const dark = usePrefersDark();
  return (
    <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </FluentProvider>
  );
}
