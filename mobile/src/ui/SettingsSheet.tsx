// Settings: the paired computer and how it's connected, voice/notification preferences, and disconnect / unpair.
import { Alert, Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { jarvis } from "../state/controller.ts";
import { useJarvis } from "./useJarvis.ts";
import { colors, font, radius } from "./theme.ts";
import { ComputerIcon, Cross } from "./icons.tsx";

export function SettingsSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const s = useJarvis();
  const connected = s.conn === "ready";
  const confirmUnpair = () => Alert.alert("Unpair this phone?", "It won't be able to reach Jarvis on your computer until you scan a new code.", [
    { text: "Cancel", style: "cancel" },
    { text: "Unpair", style: "destructive", onPress: () => { onClose(); void jarvis.unpair(); } },
  ]);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose} transparent={false}>
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
        <View style={styles.top}>
          <Text style={styles.title}>Jarvis</Text>
          <Pressable onPress={onClose} style={styles.close} accessibilityLabel="Close"><Cross size={16} color={colors.text2} /></Pressable>
        </View>
        <ScrollView contentContainerStyle={{ gap: 22 }}>
          <View style={styles.card}>
            <View style={styles.computer}>
              <View style={styles.computerIcon}><ComputerIcon size={22} color={colors.cyan} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle}>{s.computerName || "Your computer"}</Text>
                <Text style={styles.cardSub}>
                  {connected ? (s.transport === "relay" ? "Connected through the relay · end-to-end encrypted" : "Connected on your Wi-Fi · encrypted")
                    : s.conn === "starting" ? "Opening Jarvis…" : "Not connected right now"}
                </Text>
              </View>
            </View>
            <Row label={connected ? "Disconnect" : "Connect now"} onPress={() => (connected ? jarvis.disconnect() : jarvis.reconnect())} />
          </View>

          <View style={styles.card}>
            <Toggle label="Read replies aloud" hint="Always, not just after you talk" value={s.prefs.speak} onChange={(v) => jarvis.setPref("speak", v)} />
            <View style={styles.sep} />
            <Toggle label="Notifications" hint="When your computer finishes something while Jarvis is in the background" value={s.prefs.notify} onChange={(v) => jarvis.setPref("notify", v)} />
          </View>

          <View style={styles.card}>
            <Row label="Clear chat on this phone" onPress={() => { jarvis.clearChat(); onClose(); }} />
            <View style={styles.sep} />
            <Row label="Unpair this phone" danger onPress={confirmUnpair} />
          </View>
          <Text style={styles.foot}>
            {s.device ? `This ${s.device.name} is paired. ` : ""}The AI runs on your Groq account; your phone and computer talk end to end encrypted.
          </Text>
        </ScrollView>
      </View>
    </Modal>
  );
}

function Row({ label, onPress, danger }: { label: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.row, pressed && { opacity: 0.6 }]}>
      <Text style={[styles.rowText, danger && { color: colors.red }]}>{label}</Text>
    </Pressable>
  );
}
function Toggle({ label, hint, value, onChange }: { label: string; hint: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}><Text style={styles.rowText}>{label}</Text><Text style={styles.hint}>{hint}</Text></View>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: colors.mint, false: colors.surface3 }} thumbColor="#fff" />
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1, backgroundColor: colors.bgRaise, paddingHorizontal: 18, paddingTop: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 18 },
  title: { color: colors.text, fontSize: 26, fontWeight: "750" as any, letterSpacing: -0.5, fontFamily: font.family },
  close: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.surface2, alignItems: "center", justifyContent: "center" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, paddingHorizontal: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2 },
  computer: { flexDirection: "row", gap: 14, alignItems: "center", paddingVertical: 16, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line2 },
  computerIcon: { width: 44, height: 44, borderRadius: 13, backgroundColor: colors.surface2, alignItems: "center", justifyContent: "center" },
  cardTitle: { color: colors.text, fontSize: 17, fontWeight: "650" as any, fontFamily: font.family },
  cardSub: { color: colors.text3, fontSize: 13.5, marginTop: 2, fontFamily: font.family },
  row: { minHeight: 54, flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10 },
  rowText: { color: colors.text, fontSize: 16, fontFamily: font.family },
  hint: { color: colors.text3, fontSize: 13, marginTop: 2, fontFamily: font.family },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: colors.line2 },
  foot: { color: colors.text3, fontSize: 12.5, lineHeight: 18, textAlign: "center", paddingHorizontal: 12, fontFamily: font.family },
});
