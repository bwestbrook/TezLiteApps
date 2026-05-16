// Mint Time frames — six preset SVG decorations a buyer picks from before
// minting. Each frame is a self-contained <svg> markup string sized to a
// 400×400 viewBox; the capsule content (timestamp, text, image) sits in an
// inner safe area of roughly 60×60 → 340×340 absolutely positioned over the
// SVG. `frame_id` is the index into FRAMES — that's what's stored on-chain.
//
// Why one JS module instead of six .svg files: keeps the asset graph flat
// (no per-file webpack require()), and lets the SVG reference dynamic
// gradients/filters with stable ids that won't collide across frames.

const gold = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <defs>
    <linearGradient id="mt-gold-grad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#fff4c2"/>
      <stop offset="40%" stop-color="#d4a73a"/>
      <stop offset="70%" stop-color="#a37018"/>
      <stop offset="100%" stop-color="#f4d774"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="400" height="400" fill="url(#mt-gold-grad)"/>
  <rect x="30" y="30" width="340" height="340" fill="#1a1208" stroke="#7a5510" stroke-width="2"/>
  <rect x="50" y="50" width="300" height="300" fill="none" stroke="url(#mt-gold-grad)" stroke-width="6"/>
  <g fill="url(#mt-gold-grad)">
    <circle cx="50" cy="50" r="10"/>
    <circle cx="350" cy="50" r="10"/>
    <circle cx="50" cy="350" r="10"/>
    <circle cx="350" cy="350" r="10"/>
  </g>
</svg>`

const neon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <defs>
    <filter id="mt-neon-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect x="0" y="0" width="400" height="400" fill="#06081a"/>
  <rect x="30" y="30" width="340" height="340" rx="14" fill="none" stroke="#00ffe1" stroke-width="3" filter="url(#mt-neon-glow)"/>
  <rect x="50" y="50" width="300" height="300" rx="8" fill="none" stroke="#ff2dd1" stroke-width="1.5" filter="url(#mt-neon-glow)"/>
  <g filter="url(#mt-neon-glow)" fill="none" stroke="#00ffe1" stroke-width="1.5">
    <path d="M30 60 L20 60 L20 80"/>
    <path d="M370 60 L380 60 L380 80"/>
    <path d="M30 340 L20 340 L20 320"/>
    <path d="M370 340 L380 340 L380 320"/>
  </g>
</svg>`

const parchment = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <defs>
    <radialGradient id="mt-parch-grad" cx="0.5" cy="0.5" r="0.7">
      <stop offset="0%" stop-color="#fbeec1"/>
      <stop offset="70%" stop-color="#dfc488"/>
      <stop offset="100%" stop-color="#8a6a2a"/>
    </radialGradient>
    <filter id="mt-parch-rough">
      <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="3"/>
      <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.22  0 0 0 0 0.08  0 0 0 0.35 0"/>
      <feComposite in2="SourceGraphic" operator="in"/>
      <feBlend in2="SourceGraphic" mode="multiply"/>
    </filter>
  </defs>
  <rect x="0" y="0" width="400" height="400" fill="url(#mt-parch-grad)"/>
  <rect x="0" y="0" width="400" height="400" fill="url(#mt-parch-grad)" filter="url(#mt-parch-rough)" opacity="0.6"/>
  <path d="M40 50 Q200 40 360 50 L355 350 Q200 360 45 350 Z" fill="none" stroke="#5a3a10" stroke-width="2" stroke-dasharray="4 6"/>
  <text x="200" y="32" text-anchor="middle" font-family="Georgia, serif" font-size="14" fill="#5a3a10" font-style="italic">— time capsule —</text>
</svg>`

const polaroid = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <rect x="0" y="0" width="400" height="400" fill="#f6f3ea"/>
  <rect x="40" y="35" width="320" height="290" fill="#0d0d0f"/>
  <rect x="0" y="325" width="400" height="75" fill="#f6f3ea"/>
  <rect x="38" y="33" width="324" height="294" fill="none" stroke="#000" stroke-opacity="0.06" stroke-width="2"/>
</svg>`

const cosmic = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <defs>
    <radialGradient id="mt-cosmic-grad" cx="0.3" cy="0.3" r="0.9">
      <stop offset="0%" stop-color="#3a1c6e"/>
      <stop offset="60%" stop-color="#0a0a2a"/>
      <stop offset="100%" stop-color="#020010"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="400" height="400" fill="url(#mt-cosmic-grad)"/>
  <g fill="#fff">
    <circle cx="20" cy="40" r="1"/>
    <circle cx="80" cy="20" r="0.6"/>
    <circle cx="370" cy="60" r="1.2"/>
    <circle cx="340" cy="20" r="0.5"/>
    <circle cx="40" cy="380" r="0.8"/>
    <circle cx="380" cy="370" r="1"/>
    <circle cx="200" cy="14" r="0.5"/>
    <circle cx="14" cy="200" r="0.7"/>
    <circle cx="386" cy="200" r="0.6"/>
    <circle cx="200" cy="386" r="0.5"/>
    <circle cx="60" cy="100" r="0.4"/>
    <circle cx="330" cy="110" r="0.5"/>
    <circle cx="100" cy="350" r="0.6"/>
    <circle cx="290" cy="350" r="0.4"/>
  </g>
  <rect x="40" y="40" width="320" height="320" fill="none" stroke="#9b88ff" stroke-width="1" stroke-opacity="0.6"/>
  <rect x="30" y="30" width="340" height="340" fill="none" stroke="#5a4ab0" stroke-width="1" stroke-opacity="0.5"/>
</svg>`

const minimal = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
  <rect x="0" y="0" width="400" height="400" fill="#fafaf6"/>
  <rect x="20" y="20" width="360" height="360" fill="none" stroke="#111" stroke-width="1"/>
  <rect x="30" y="30" width="340" height="340" fill="#0e0e10"/>
  <line x1="30" y1="350" x2="370" y2="350" stroke="#888" stroke-width="0.5"/>
</svg>`

// Each entry maps to a `frame_id` stored on-chain. ORDER MUST BE STABLE —
// changing it would re-label every existing token's frame. The contract
// asserts `frame_id < 6`, so adding a 7th here also needs a contract bump.
export const FRAMES = [
  { id: 0, name: 'Gold',      svg: gold,      textOn: '#f4d774' },
  { id: 1, name: 'Neon',      svg: neon,      textOn: '#00ffe1' },
  { id: 2, name: 'Parchment', svg: parchment, textOn: '#3a2410' },
  { id: 3, name: 'Polaroid',  svg: polaroid,  textOn: '#ffffff' },
  { id: 4, name: 'Cosmic',    svg: cosmic,    textOn: '#cfc5ff' },
  { id: 5, name: 'Minimal',   svg: minimal,   textOn: '#f0f0f0' },
]

export const FRAME_BY_ID = Object.fromEntries(FRAMES.map((f) => [f.id, f]))
