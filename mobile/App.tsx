import { useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { jarvis } from "./src/state/controller.ts";
import { useJarvis } from "./src/ui/useJarvis.ts";
import { ChatScreen } from "./src/ui/ChatScreen.tsx";
import { PairScreen } from "./src/ui/PairScreen.tsx";
import { SettingsSheet } from "./src/ui/SettingsSheet.tsx";
import { colors } from "./src/ui/theme.ts";
import { Orb } from "./src/ui/Orb.tsx";

export default function App() {
  const booted = useJarvis((s) => s.booted);
  const paired = useJarvis((s) => !!s.device);
  const [settings, setSettings] = useState(false);
  useEffect(() => { void jarvis.boot(); }, []);
  return (
    <SafeAreaProvider>
      <View style={styles.root}>
        <StatusBar style="light" />
        {!booted ? <View style={styles.splash}><Orb size={72} busy /></View>
          : paired ? <ChatScreen onOpenSettings={() => setSettings(true)} /> : <PairScreen />}
        <SettingsSheet visible={settings && paired} onClose={() => setSettings(false)} />
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  splash: { flex: 1, alignItems: "center", justifyContent: "center" },
});
