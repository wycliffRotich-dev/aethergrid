/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        muted: {
          purple: "#6B5B7A",
          "purple-hover": "#7A6B8A",
        },
      },
    },
  },
  plugins: [],
};