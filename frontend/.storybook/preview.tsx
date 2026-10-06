import type { Decorator, Preview } from "@storybook/react-vite";
import { useEffect } from "react";

import "../src/index.css";

/** Every story renders in the chosen theme (docs/ui: dark default, light complete). */
const withTheme: Decorator = (Story, context) => {
  const theme = context.globals.theme === "light" ? "light" : "dark";
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  return (
    <div className="min-h-screen bg-bg p-6 text-text">
      <Story />
    </div>
  );
};

const preview: Preview = {
  decorators: [withTheme],
  globalTypes: {
    theme: {
      description: "Theme",
      toolbar: { icon: "mirror", items: ["dark", "light"], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "dark" },
  parameters: { layout: "fullscreen" },
};

export default preview;
