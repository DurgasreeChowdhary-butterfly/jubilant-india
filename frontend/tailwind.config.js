/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base:    "#0c0c0f",
        surface: "#141418",
        rim:     "#1e1e26",
        accent:  "#e8ff6e",
        muted:   "#9090a8",
      },
    },
  },
  plugins: [],
};
