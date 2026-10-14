// The Jarvis orb (the desktop app's logo), optionally breathing while Jarvis works. Animations run on the native
// driver (opacity/transform only), so they never cost JS-thread time.
import { useEffect, useRef } from "react";
import { Animated, Easing, View } from "react-native";
import Svg, { Circle, Defs, Ellipse, LinearGradient, RadialGradient, Stop } from "react-native-svg";

export function Orb({ size = 40, busy = false }: { size?: number; busy?: boolean }) {
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!busy) { pulse.stopAnimation(); pulse.setValue(0); return; }
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [busy, pulse]);
  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 0.9] });
  const glow = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.55, 1] });
  return (
    <View style={{ width: size, height: size }}>
      <Animated.View style={{ position: "absolute", inset: 0, opacity: glow, transform: [{ scale }] }}>
        <Svg width={size} height={size} viewBox="0 0 32 32">
          <Defs>
            <LinearGradient id="og" x1="0" y1="0" x2="1" y2="1"><Stop offset="0" stopColor="#5EE0FF" /><Stop offset="1" stopColor="#A58BFF" /></LinearGradient>
            <RadialGradient id="oh"><Stop offset="0" stopColor="#4FD8FF" stopOpacity="0.45" /><Stop offset="1" stopColor="#4FD8FF" stopOpacity="0" /></RadialGradient>
          </Defs>
          <Circle cx="16" cy="16" r="13" fill="url(#oh)" />
          <Circle cx="16" cy="16" r="6" fill="url(#og)" />
          <Ellipse cx="16" cy="16" rx="14" ry="6" fill="none" stroke="url(#og)" strokeWidth="1.4" opacity={0.9} transform="rotate(-25 16 16)" />
          <Ellipse cx="16" cy="16" rx="14" ry="6" fill="none" stroke="url(#og)" strokeWidth="1.4" opacity={0.5} transform="rotate(35 16 16)" />
        </Svg>
      </Animated.View>
    </View>
  );
}
