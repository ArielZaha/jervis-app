// Line icons drawn with react-native-svg (no icon font to load: faster startup, crisp at any density).
import Svg, { Circle, Path, Rect } from "react-native-svg";

type P = { size?: number; color?: string; stroke?: number };
const base = (size = 22) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none" });

export const Mic = ({ size, color = "#fff", stroke = 2 }: P) => (
  <Svg {...base(size)}><Rect x={9} y={3} width={6} height={11} rx={3} stroke={color} strokeWidth={stroke} />
    <Path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" stroke={color} strokeWidth={stroke} strokeLinecap="round" /></Svg>);
export const Send = ({ size, color = "#fff", stroke = 2.4 }: P) => (
  <Svg {...base(size)}><Path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" /></Svg>);
export const Stop = ({ size, color = "#fff" }: P) => (<Svg {...base(size)}><Rect x={7} y={7} width={10} height={10} rx={2.5} fill={color} /></Svg>);
export const PhoneIcon = ({ size, color = "#fff", stroke = 1.9 }: P) => (
  <Svg {...base(size)}><Rect x={6.5} y={2.5} width={11} height={19} rx={3} stroke={color} strokeWidth={stroke} /><Path d="M11 18.5h2" stroke={color} strokeWidth={stroke} strokeLinecap="round" /></Svg>);
export const ComputerIcon = ({ size, color = "#fff", stroke = 1.9 }: P) => (
  <Svg {...base(size)}><Rect x={3} y={4} width={18} height={12} rx={2.2} stroke={color} strokeWidth={stroke} /><Path d="M8.5 20h7M12 16v4" stroke={color} strokeWidth={stroke} strokeLinecap="round" /></Svg>);
export const Gear = ({ size, color = "#fff", stroke = 1.8 }: P) => (
  <Svg {...base(size)}><Circle cx={12} cy={12} r={3.2} stroke={color} strokeWidth={stroke} />
    <Path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" stroke={color} strokeWidth={stroke} /></Svg>);
export const Check = ({ size, color = "#fff", stroke = 2.6 }: P) => (
  <Svg {...base(size)}><Path d="M5 12.5l4.5 4.5L19 7.5" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" /></Svg>);
export const Cross = ({ size, color = "#fff", stroke = 2.4 }: P) => (
  <Svg {...base(size)}><Path d="M6.5 6.5l11 11M17.5 6.5l-11 11" stroke={color} strokeWidth={stroke} strokeLinecap="round" /></Svg>);
export const Scan = ({ size, color = "#fff", stroke = 2 }: P) => (
  <Svg {...base(size)}><Path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M7 12h10" stroke={color} strokeWidth={stroke} strokeLinecap="round" /></Svg>);
export const Bolt = ({ size, color = "#fff" }: P) => (
  <Svg {...base(size)}><Path d="M13 2.5L4.5 13.5H11l-1 8 8.5-11H12l1-8z" fill={color} /></Svg>);
