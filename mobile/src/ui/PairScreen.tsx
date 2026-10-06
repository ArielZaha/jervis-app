// First run: pair with the computer by scanning the QR code "Connect my phone" shows (in-app camera), or by pasting
// its link. Same Wi-Fi, once. After that the app reconnects on its own every time it opens.
import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { CameraView, useCameraPermissions } from "expo-camera";
import { LinearGradient } from "expo-linear-gradient";
import { jarvis } from "../state/controller.ts";
import { colors, font, radius } from "./theme.ts";
import { Orb } from "./Orb.tsx";
import { Cross, Scan } from "./icons.tsx";

export function PairScreen() {
  const insets = useSafeAreaInsets();
  const [scanning, setScanning] = useState(false);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [permission, requestPermission] = useCameraPermissions();

  const tryPair = async (input: string) => {
    if (busy) return;
    setScanning(false);
    setBusy(true);
    setError("");
    const problem = await jarvis.pairWith(input);
    setBusy(false);
    if (problem) setError(problem);
  };
  const openScanner = async () => {
    setError("");
    if (!permission?.granted) {
      const p = await requestPermission();
      if (!p.granted) { setError("Camera access is off, so paste the link instead (or allow the camera in Settings)."); return; }
    }
    setScanning(true);
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding">
      <ScrollView contentContainerStyle={[styles.wrap, { paddingTop: insets.top + 40, paddingBottom: insets.bottom + 24 }]} keyboardShouldPersistTaps="handled">
        <View style={styles.hero}>
          <Orb size={96} busy={busy} />
          <Text style={styles.title}>Your Jarvis,{"\n"}everywhere.</Text>
          <Text style={styles.lead}>One assistant on your phone and your computer. Pair once, and it connects by itself from then on.</Text>
        </View>

        <View style={styles.steps}>
          <Step n="1" text={<>On your computer, say <Text style={styles.b}>“Connect my phone”</Text>.</>} />
          <Step n="2" text={<>Scan the QR code it shows. Same Wi-Fi, just this once.</>} />
        </View>

        <Pressable onPress={openScanner} disabled={busy} style={({ pressed }) => [pressed && { transform: [{ scale: 0.98 }] }]}>
          <LinearGradient colors={["#5EE0FF", "#7D9DFF", "#A58BFF"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.primary}>
            {busy ? <ActivityIndicator color={colors.youText} /> : <Scan size={22} color={colors.youText} />}
            <Text style={styles.primaryText}>{busy ? "Pairing…" : "Scan the code"}</Text>
          </LinearGradient>
        </Pressable>

        <View style={styles.or}><View style={styles.orLine} /><Text style={styles.orText}>or paste the link</Text><View style={styles.orLine} /></View>
        <View style={styles.pasteRow}>
          <TextInput value={link} onChangeText={setLink} placeholder="http://192.168.1.20:8766/?code=123456" placeholderTextColor={colors.text3}
                     style={styles.paste} autoCapitalize="none" autoCorrect={false} keyboardType={Platform.OS === "ios" ? "url" : "default"}
                     returnKeyType="go" onSubmitEditing={() => void tryPair(link)} keyboardAppearance="dark" />
          <Pressable onPress={() => void tryPair(link)} disabled={!link.trim() || busy} style={({ pressed }) => [styles.pasteBtn, (!link.trim() || busy) && { opacity: 0.4 }, pressed && { opacity: 0.7 }]}>
            <Text style={styles.pasteBtnText}>Pair</Text>
          </Pressable>
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>

      <Modal visible={scanning} animationType="slide" onRequestClose={() => setScanning(false)} presentationStyle="fullScreen">
        <View style={styles.scanner}>
          <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
                      onBarcodeScanned={busy ? undefined : (r) => void tryPair(r.data)} />
          <View style={[styles.scanTop, { paddingTop: insets.top + 12 }]}>
            <Text style={styles.scanTitle}>Scan the code on your computer</Text>
            <Pressable onPress={() => setScanning(false)} style={styles.scanClose} accessibilityLabel="Close"><Cross size={18} color="#fff" /></Pressable>
          </View>
          <View style={styles.frame} />
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

function Step({ n, text }: { n: string; text: React.ReactNode }) {
  return (
    <View style={styles.step}>
      <View style={styles.stepN}><Text style={styles.stepNText}>{n}</Text></View>
      <Text style={styles.stepText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexGrow: 1, paddingHorizontal: 24, justifyContent: "center", gap: 18, maxWidth: 480, width: "100%", alignSelf: "center" },
  hero: { alignItems: "center", gap: 14, marginBottom: 8 },
  title: { color: colors.text, fontSize: 32, lineHeight: 37, fontWeight: "750" as any, textAlign: "center", letterSpacing: -0.8, marginTop: 8, fontFamily: font.family },
  lead: { color: colors.text2, fontSize: 16, lineHeight: 23, textAlign: "center", maxWidth: 320, fontFamily: font.family },
  steps: { gap: 10 },
  step: { flexDirection: "row", gap: 14, alignItems: "center", padding: 16, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2 },
  stepN: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.surface3, alignItems: "center", justifyContent: "center" },
  stepNText: { color: colors.text, fontWeight: "700", fontSize: 14 },
  stepText: { color: colors.text2, fontSize: 15.5, lineHeight: 21, flex: 1, fontFamily: font.family },
  b: { color: colors.text, fontWeight: "650" as any },
  primary: { height: 56, borderRadius: radius.pill, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10 },
  primaryText: { color: colors.youText, fontSize: 17, fontWeight: "700", fontFamily: font.family },
  or: { flexDirection: "row", alignItems: "center", gap: 12 },
  orLine: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: colors.line2 },
  orText: { color: colors.text3, fontSize: 13, fontFamily: font.family },
  pasteRow: { flexDirection: "row", gap: 8 },
  paste: { flex: 1, height: 50, borderRadius: radius.md, backgroundColor: colors.surface, color: colors.text, paddingHorizontal: 14, fontSize: 14.5, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2 },
  pasteBtn: { height: 50, paddingHorizontal: 20, borderRadius: radius.md, backgroundColor: colors.surface2, alignItems: "center", justifyContent: "center" },
  pasteBtnText: { color: colors.text, fontSize: 16, fontWeight: "650" as any },
  error: { color: colors.red, fontSize: 14.5, lineHeight: 20, textAlign: "center", fontFamily: font.family },
  scanner: { flex: 1, backgroundColor: "#000" },
  scanTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 20, paddingBottom: 12, backgroundColor: "rgba(0,0,0,0.45)" },
  scanTitle: { color: "#fff", fontSize: 17, fontWeight: "650" as any },
  scanClose: { width: 38, height: 38, borderRadius: 19, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
  frame: { position: "absolute", alignSelf: "center", top: "32%", width: 240, height: 240, borderRadius: 28, borderWidth: 3, borderColor: "rgba(94,224,255,0.9)" },
});
