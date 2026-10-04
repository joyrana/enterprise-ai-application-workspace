import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../App";

export function renderAt(path: string): ReturnType<typeof render> {
  return renderWithProviders(<AppRoutes />, path);
}

export function renderWithProviders(ui: ReactElement, path = "/"): ReturnType<typeof render> {
  return render(
    <FluentProvider theme={webLightTheme}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </FluentProvider>,
  );
}
