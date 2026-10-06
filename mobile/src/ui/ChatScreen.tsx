// The main Jarvis screen: header with live connection status, the Phone/Computer switch, the conversation, and the
// composer with voice. Rows are memoized and the list is inverted (newest at the bottom, no scroll jumps).
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Animated, Easing, FlatList, Keyboard, KeyboardAvoidingView, Linking, Platform, Pressable,
  StyleSheet, Text, TextInput, View, type LayoutChangeEvent, type ListRenderItem,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";
import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { jarvis, type Msg } from "../state/controller.ts";
import type { Mode } from "../core/agent.ts";
import type { ConnState } from "../core/protocol.ts";
import { useJarvis } from "./useJarvis.ts";
import { brandGradient, colors, font, radius } from "./theme.ts";
import { Check, ComputerIcon, Cross, Gear, Mic, PhoneIcon, Send, Stop } from "./icons.tsx";
import { Orb } from "./Orb.tsx";

const IOS = Platform.OS === "ios";

export function ChatScreen({ onOpenSettings }: { onOpenSettings: () => void }) {
  const insets = useSafeAreaInsets();
  const messages = useJarvis((s) => s.messages);
  const thinking = useJarvis((s) => s.thinking);
  const mode = useJarvis((s) => s.mode);
  const data = useMemo(() => [...messages].reverse(), [messages]);
  const [kbOpen, setKbOpen] = useState(false);

  useEffect(() => {
    const show = Keyboard.addListener(IOS ? "keyboardWillShow" : "keyboardDidShow", () => setKbOpen(true));
    const hide = Keyboard.addListener(IOS ? "keyboardWillHide" : "keyboardDidHide", () => setKbOpen(false));
    return () => { show.remove(); hide.remove(); };
  }, []);

  const renderItem: ListRenderItem<Msg> = useCallback(({ item, index }) => {
    const older = data[index + 1];   // inverted: the next item is the previous message
    const grouped = !!older && older.kind === item.kind && item.kind !== "activity" && item.ts - older.ts < 120000;
    return <Row msg={item} grouped={grouped} />;
  }, [data]);

  return (
    <KeyboardAvoidingView style={styles.fill} behavior="padding">
      <Header topInset={insets.top} onOpenSettings={onOpenSettings} />
      <FlatList
        style={styles.fill}
        data={data}
        inverted
        keyExtractor={(m) => m.id}
        renderItem={renderItem}
        contentContainerStyle={[styles.listContent, !data.length && styles.listEmpty]}
        ListHeaderComponent={thinking ? <Thinking where={thinking} /> : null}
        ListEmptyComponent={<Empty mode={mode} />}
        keyboardDismissMode="interactive"
        keyboardShouldPersistTaps="handled"
        removeClippedSubviews={Platform.OS === "android"}
        initialNumToRender={14}
        maxToRenderPerBatch={10}
        windowSize={11}
        showsVerticalScrollIndicator={false}
      />
      <Composer bottomInset={kbOpen ? 0 : insets.bottom} />
    </KeyboardAvoidingView>
  );
}

// ------------------------------------------------------------------ header + connection
const STATUS: Record<ConnState, { text: string; tone: "ok" | "busy" | "off" }> = {
  ready: { text: "Connected", tone: "ok" },
  connecting: { text: "Connecting…", tone: "busy" },
  waiting: { text: "Reconnecting…", tone: "busy" },
  starting: { text: "Opening Jarvis on your computer…", tone: "busy" },
  closed: { text: "Jarvis is closed on your computer", tone: "off" },
  unreachable: { text: "Computer offline", tone: "off" },
  offline: { text: "No internet", tone: "off" },
  stopped: { text: "Disconnected", tone: "off" },
  replaced: { text: "In use on another device", tone: "off" },
  ended: { text: "Disconnected by your computer", tone: "off" },
  unpaired: { text: "Not paired", tone: "off" },
  idle: { text: "Not connected", tone: "off" },
};

function Header({ topInset, onOpenSettings }: { topInset: number; onOpenSettings: () => void }) {
  const conn = useJarvis((s) => s.conn);
  const computerName = useJarvis((s) => s.computerName);
  const transport = useJarvis((s) => s.transport);
  const thinking = useJarvis((s) => s.thinking);
  const status = STATUS[conn];
  const canAct = conn === "closed" || conn === "stopped" || conn === "ended" || conn === "replaced" || conn === "unreachable";
  const line = conn === "ready"
    ? `${computerName || "Your computer"}${transport === "relay" ? " · away from home" : ""}`
    : status.text;
  const inner = (
    <View style={[styles.header, { paddingTop: topInset + 6 }]}>
      <View style={styles.headerRow}>
        <View>
          <Orb size={38} busy={!!thinking} />
          <View style={[styles.presence, { backgroundColor: status.tone === "ok" ? colors.mint : status.tone === "busy" ? colors.amber : colors.text3 }]} />
        </View>
        <View style={styles.headerText}>
          <Text style={styles.title}>Jarvis</Text>
          <Pressable disabled={!canAct} onPress={() => jarvis.reconnect()} hitSlop={8} accessibilityRole={canAct ? "button" : undefined}>
            <Text style={styles.subtitle} numberOfLines={1}>
              <Text style={{ color: status.tone === "ok" ? colors.text2 : colors.text3 }}>{line}</Text>
              {canAct ? <Text style={styles.subtitleAction}>{conn === "closed" ? "  Open Jarvis" : "  Retry"}</Text> : null}
            </Text>
          </Pressable>
        </View>
        <Pressable onPress={onOpenSettings} style={({ pressed }) => [styles.iconBtn, pressed && styles.pressed]} accessibilityLabel="Settings" hitSlop={6}>
          <Gear size={21} color={colors.text2} />
        </Pressable>
      </View>
      <ModeSwitch />
    </View>
  );
  // iOS: translucent material like the system's own bars. Android: solid (blur is costly on mid-range GPUs).
  return IOS ? <BlurView intensity={40} tint="dark" style={styles.headerWrap}>{inner}</BlurView> : <View style={[styles.headerWrap, styles.headerSolid]}>{inner}</View>;
}

function ModeSwitch() {
  const mode = useJarvis((s) => s.mode);
  const conn = useJarvis((s) => s.conn);
  const [width, setWidth] = useState(0);
  const x = useRef(new Animated.Value(mode === "phone" ? 0 : 1)).current;
  useEffect(() => {
    Animated.spring(x, { toValue: mode === "phone" ? 0 : 1, useNativeDriver: true, damping: 18, stiffness: 220, mass: 0.7 }).start();
  }, [mode, x]);
  const half = (width - 8) / 2;
  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);
  const seg = (m: Mode, label: string, Icon: typeof PhoneIcon) => {
    const active = mode === m;
    return (
      <Pressable key={m} style={styles.segment} onPress={() => jarvis.setMode(m)} accessibilityRole="tab" accessibilityState={{ selected: active }}>
        <Icon size={17} color={active ? colors.youText : colors.text2} />
        <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{label}</Text>
        {m === "computer" ? <View style={[styles.segDot, { backgroundColor: conn === "ready" ? colors.mint : conn === "starting" || conn === "connecting" || conn === "waiting" ? colors.amber : colors.text3 }]} /> : null}
      </Pressable>
    );
  };
  return (
    <View style={styles.switch} onLayout={onLayout}>
      {width > 0 && (
        <Animated.View style={[styles.switchPill, { width: half, transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [0, half] }) }] }]}>
          <LinearGradient colors={[...brandGradient]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={StyleSheet.absoluteFill} />
        </Animated.View>
      )}
      {seg("phone", "Phone", PhoneIcon)}
      {seg("computer", "Computer", ComputerIcon)}
    </View>
  );
}

// ------------------------------------------------------------------ messages
const Row = memo(function Row({ msg, grouped }: { msg: Msg; grouped: boolean }) {
  switch (msg.kind) {
    case "user":
      return (
        <View style={[styles.rowYou, grouped && styles.grouped]}>
          <LinearGradient colors={[...brandGradient]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[styles.bubbleYou, msg.queued && { opacity: 0.55 }]}>
            <Text style={styles.youText} selectable>{msg.text}</Text>
          </LinearGradient>
          {msg.queued ? <Text style={styles.meta}>Waiting for your computer…</Text>
            : msg.via === "computer" && !grouped ? <Text style={styles.meta}>{msg.voice ? "🎙 " : ""}to your computer</Text>
            : msg.voice && !grouped ? <Text style={styles.meta}>🎙 voice</Text> : null}
        </View>
      );
    case "jarvis":
      return (
        <View style={[styles.rowJarvis, grouped && styles.grouped]}>
          {!grouped && (
            <View style={styles.speaker}>
              <Orb size={18} />
              <Text style={styles.speakerName}>Jarvis</Text>
              {msg.where === "computer" ? <Tag where="computer" /> : msg.where === "phone" ? <Tag where="phone" /> : null}
              <Text style={styles.speakerTime}>{timeLabel(msg.ts)}</Text>
            </View>
          )}
          <View style={styles.jarvisBody}>
            <View style={styles.rule} />
            <RichText text={msg.text} />
          </View>
          {msg.quick ? (
            <View style={styles.quickRow}>
              {msg.quick.map((q) => (
                <Pressable key={q} onPress={() => jarvis.quickReply(q)} style={({ pressed }) => [styles.quick, pressed && styles.pressed]}>
                  <Text style={styles.quickText}>{q}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      );
    case "activity":
      return <ActivityChip msg={msg} />;
    case "confirm":
      return (
        <View style={styles.confirm}>
          <Text style={styles.confirmTitle}>{msg.text}</Text>
          {msg.detail ? <Text style={styles.confirmDetail}>{msg.detail}</Text> : null}
          {msg.state === "open" ? (
            <View style={styles.confirmRow}>
              <Pressable onPress={() => jarvis.answerConfirm(msg.id, false)} style={({ pressed }) => [styles.btn, styles.btnQuiet, pressed && styles.pressed]}>
                <Text style={styles.btnQuietText}>Cancel</Text>
              </Pressable>
              <Pressable onPress={() => jarvis.answerConfirm(msg.id, true)} style={({ pressed }) => [styles.btn, styles.btnPrimary, pressed && styles.pressed]}>
                <Text style={styles.btnPrimaryText}>Confirm</Text>
              </Pressable>
            </View>
          ) : <Text style={[styles.confirmDone, { color: msg.state === "yes" ? colors.mint : colors.text3 }]}>{msg.state === "yes" ? "Confirmed" : "Cancelled"}</Text>}
        </View>
      );
    case "note":
      return (
        <View style={[styles.note, msg.tone === "err" && styles.noteErr]}>
          {msg.tone === "ok" ? <Check size={14} color={colors.mint} /> : msg.tone === "err" ? <Cross size={13} color={colors.red} /> : null}
          <Text style={[styles.noteText, msg.tone === "ok" && { color: colors.mint }, msg.tone === "err" && { color: colors.red }]}>{msg.text}</Text>
        </View>
      );
  }
});

function Tag({ where }: { where: "phone" | "computer" }) {
  const Icon = where === "phone" ? PhoneIcon : ComputerIcon;
  return (
    <View style={styles.tag}>
      <Icon size={11} color={colors.text3} stroke={2.2} />
      <Text style={styles.tagText}>{where === "phone" ? "Phone" : "Computer"}</Text>
    </View>
  );
}

function ActivityChip({ msg }: { msg: Extract<Msg, { kind: "activity" }> }) {
  const color = msg.status === "failed" ? colors.red : msg.status === "done" ? colors.mint : colors.text2;
  return (
    <View style={styles.activity}>
      <View style={[styles.activityIcon, { borderColor: msg.status === "running" ? colors.line2 : color }]}>
        {msg.status === "running" ? <ActivityIndicator size="small" color={colors.cyan} style={{ transform: [{ scale: 0.7 }] }} />
          : msg.status === "done" ? <Check size={12} color={color} stroke={3} /> : <Cross size={11} color={color} stroke={3} />}
      </View>
      <Text style={[styles.activityText, msg.status !== "running" && { color: colors.text2 }]} numberOfLines={2}>{msg.text}</Text>
      {msg.where !== "none" ? <Tag where={msg.where} /> : null}
    </View>
  );
}

function Thinking({ where }: { where: "phone" | "computer" }) {
  const dots = [useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current];
  useEffect(() => {
    const anims = dots.map((v, i) => Animated.loop(Animated.sequence([
      Animated.delay(i * 140),
      Animated.timing(v, { toValue: 1, duration: 320, easing: Easing.out(Easing.quad), useNativeDriver: true }),
      Animated.timing(v, { toValue: 0, duration: 320, easing: Easing.in(Easing.quad), useNativeDriver: true }),
      Animated.delay((2 - i) * 140 + 200),
    ])));
    anims.forEach((a) => a.start());
    return () => anims.forEach((a) => a.stop());
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const tint = [colors.cyan, colors.indigo, colors.violet];
  return (
    <View style={styles.thinking}>
      <View style={styles.rule} />
      <View style={styles.dots}>
        {dots.map((v, i) => (
          <Animated.View key={i} style={[styles.dot, { backgroundColor: tint[i], opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1] }),
            transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [0, -4] }) }] }]} />
        ))}
      </View>
      <Text style={styles.thinkingText}>{where === "computer" ? "Working on your computer" : ""}</Text>
    </View>
  );
}

// A small, safe subset of Markdown: **bold**, `code`, ``` blocks ```, bullet lines, and tappable links.
function RichText({ text }: { text: string }) {
  const parts = text.split(/```/);
  return (
    <View style={{ flex: 1, gap: 6 }}>
      {parts.map((part, i) => i % 2 === 1
        ? <Text key={i} style={styles.codeBlock} selectable>{part.replace(/^\w*\n/, "").replace(/\n$/, "")}</Text>
        : part.split(/\n{2,}/).filter((p) => p.trim()).map((para, j) => (
          <Text key={`${i}-${j}`} style={styles.jarvisText} selectable>
            {para.split("\n").map((line, k, arr) => (
              <Text key={k}>{/^\s*[-*•]\s+/.test(line) ? "•  " : ""}{inline(line.replace(/^\s*[-*•]\s+/, ""))}{k < arr.length - 1 ? "\n" : ""}</Text>
            ))}
          </Text>
        )))}
    </View>
  );
}
function inline(line: string) {
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|(https?:\/\/[^\s)]+[^\s).,;:!?])/g;
  let last = 0, m: RegExpExecArray | null, n = 0;
  while ((m = re.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index));
    if (m[1]) out.push(<Text key={n++} style={{ fontWeight: "700" }}>{m[1]}</Text>);
    else if (m[2]) out.push(<Text key={n++} style={styles.inlineCode}>{m[2]}</Text>);
    else if (m[3]) { const url = m[3]; out.push(<Text key={n++} style={styles.link} onPress={() => Linking.openURL(url)}>{url}</Text>); }
    last = re.lastIndex;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

const timeLabel = (ts: number) => new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

// ------------------------------------------------------------------ empty state
const SUGGEST: Record<Mode, Array<[string, string]>> = {
  phone: [["Play music", "Find Radiohead on Spotify"], ["Nearby", "Find the nearest coffee shop"],
          ["Timer", "Set a timer for 10 minutes"], ["The news", "What's the latest on GTA 6?"]],
  computer: [["Spotify", "Play Radiohead on Spotify"], ["YouTube", "Open YouTube"],
             ["Take control", "Take control and open Chrome"], ["Weather", "What's the weather today?"]],
};

function Empty({ mode }: { mode: Mode }) {
  return (
    <View style={styles.empty}>
      <Orb size={56} />
      <Text style={styles.emptyTitle}>Hello there,{"\n"}<Text style={{ color: colors.cyan }}>Jarvis is here for you.</Text></Text>
      <Text style={styles.emptySub}>{mode === "phone" ? "Ask anything, or tell me what to do on this phone. Say “on my computer” for your computer." : "Everything you say goes to Jarvis on your computer."}</Text>
      <View style={styles.suggestions}>
        {SUGGEST[mode].map(([title, say]) => (
          <Pressable key={say} onPress={() => void jarvis.send(say)} style={({ pressed }) => [styles.suggestion, pressed && styles.pressed]}>
            <Text style={styles.suggestionTitle}>{title}</Text>
            <Text style={styles.suggestionText}>{say}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.credit}>Created by Ariel and Shalev</Text>
    </View>
  );
}

// ------------------------------------------------------------------ composer + voice
function Composer({ bottomInset }: { bottomInset: number }) {
  const mode = useJarvis((s) => s.mode);
  const recording = useJarvis((s) => s.recording);
  const transcribing = useJarvis((s) => s.transcribing);
  const [text, setText] = useState("");
  const [height, setHeight] = useState(22);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const startedAt = useRef(0);
  const [elapsed, setElapsed] = useState(0);
  const pressAt = useRef(0);

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 250);
    return () => clearInterval(t);
  }, [recording]);

  const hasText = text.trim().length > 0;
  const submit = () => {
    if (!hasText) return;
    const value = text;
    setText("");
    setHeight(22);
    void jarvis.send(value);
  };

  const start = async () => {
    const perm = await requestRecordingPermissionsAsync();
    if (!perm.granted) { jarvis.handleRecording(null); return; }
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
    startedAt.current = Date.now();
    setElapsed(0);
    jarvis.setRecording(true);
  };
  const finish = async (cancel = false) => {
    try { await recorder.stop(); } catch { /* not recording */ }
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {});
    const long = Date.now() - startedAt.current > 600;
    void jarvis.handleRecording(cancel || !long ? null : recorder.uri, Platform.OS === "web" ? "audio/webm" : "audio/m4a");
  };

  // Tap to start / tap to stop, or press-and-hold and release to send.
  const onPressIn = () => { pressAt.current = Date.now(); if (!recording && !hasText) void start(); };
  const onPressOut = () => { if (recording && Date.now() - pressAt.current > 450) void finish(); };
  const onPress = () => {
    if (hasText) return submit();
    if (recording && Date.now() - pressAt.current <= 450 && Date.now() - startedAt.current > 700) void finish();
  };

  const placeholder = mode === "phone" ? "Ask Jarvis…" : "Tell your computer…";
  return (
    <View style={[styles.composerWrap, { paddingBottom: Math.max(bottomInset, 10) }]}>
      <View style={styles.composer}>
        <View style={[styles.field, recording && styles.fieldRec]}>
          {recording ? (
            <View style={styles.recBar}>
              <View style={styles.recDot} />
              <Text style={styles.recTime}>{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</Text>
              <Text style={styles.recHint}>Release or tap to send</Text>
              <Pressable onPress={() => void finish(true)} hitSlop={10}><Text style={styles.recCancel}>Cancel</Text></Pressable>
            </View>
          ) : transcribing ? (
            <View style={styles.recBar}><ActivityIndicator size="small" color={colors.cyan} /><Text style={styles.recHint}>Listening to that…</Text></View>
          ) : (
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder={placeholder}
              placeholderTextColor={colors.text3}
              style={[styles.input, { height: Math.min(Math.max(22, height), 132) }]}
              multiline
              onContentSizeChange={(e) => setHeight(e.nativeEvent.contentSize.height)}
              submitBehavior="submit"
              onSubmitEditing={submit}
              onKeyPress={Platform.OS === "web" ? (e) => {
                // hardware keyboards: Enter sends, Shift+Enter is a new line (phones use the Send key above)
                const ev = e.nativeEvent as unknown as { key: string; shiftKey?: boolean };
                if (ev.key === "Enter" && !ev.shiftKey) { (e as unknown as { preventDefault(): void }).preventDefault(); submit(); }
              } : undefined}
              returnKeyType="send"
              enablesReturnKeyAutomatically
              autoCorrect
              autoCapitalize="sentences"
              keyboardAppearance="dark"
              selectionColor={colors.cyan}
            />
          )}
        </View>
        <Pressable
          onPressIn={onPressIn} onPressOut={onPressOut} onPress={onPress}
          disabled={transcribing}
          accessibilityLabel={hasText ? "Send" : recording ? "Stop and send" : "Talk to Jarvis"}
          style={({ pressed }) => [styles.action, hasText && styles.actionSend, recording && styles.actionRec, pressed && { transform: [{ scale: 0.93 }] }]}
        >
          {hasText ? <Send size={22} color={colors.bg} /> : recording ? <Stop size={20} color="#fff" /> : <Mic size={23} color={colors.text} />}
        </Pressable>
      </View>
    </View>
  );
}

// ------------------------------------------------------------------ styles
const styles = StyleSheet.create({
  fill: { flex: 1 },
  pressed: { opacity: 0.7 },
  headerWrap: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line, zIndex: 2 },
  headerSolid: { backgroundColor: colors.bg },
  header: { paddingHorizontal: 16, paddingBottom: 10, gap: 10 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  presence: { position: "absolute", right: -1, bottom: -1, width: 12, height: 12, borderRadius: 6, borderWidth: 2.5, borderColor: colors.bg },
  headerText: { flex: 1, minWidth: 0 },
  title: { color: colors.text, fontSize: 18, fontWeight: "700", letterSpacing: -0.3, fontFamily: font.family },
  subtitle: { fontSize: 13, marginTop: 1, fontFamily: font.family },
  subtitleAction: { color: colors.cyan, fontWeight: "600" },
  iconBtn: { width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  switch: { flexDirection: "row", backgroundColor: colors.surface, borderRadius: radius.pill, padding: 4, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2 },
  switchPill: { position: "absolute", top: 4, bottom: 4, left: 4, borderRadius: radius.pill, overflow: "hidden" },
  segment: { flex: 1, height: 38, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7 },
  segmentText: { color: colors.text2, fontSize: 15, fontWeight: "600", fontFamily: font.family },
  segmentTextActive: { color: colors.youText },
  segDot: { width: 6, height: 6, borderRadius: 3, marginLeft: 2 },
  listContent: { paddingHorizontal: 16, paddingVertical: 14 },
  listEmpty: { flexGrow: 1, justifyContent: "flex-end" },
  grouped: { marginTop: 4 },
  rowYou: { alignItems: "flex-end", marginTop: 14 },
  bubbleYou: { maxWidth: "84%", paddingHorizontal: 15, paddingVertical: 10, borderRadius: radius.lg, borderBottomRightRadius: 8 },
  youText: { color: colors.youText, fontSize: 16, lineHeight: 22, fontWeight: "500", fontFamily: font.family },
  meta: { color: colors.text3, fontSize: 11.5, marginTop: 4, marginRight: 4, fontFamily: font.family },
  rowJarvis: { marginTop: 16 },
  speaker: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 6 },
  speakerName: { color: colors.text2, fontSize: 13, fontWeight: "650" as any, fontFamily: font.family },
  speakerTime: { color: colors.text3, fontSize: 12, fontFamily: font.family },
  jarvisBody: { flexDirection: "row", gap: 13 },
  rule: { width: 2, borderRadius: 1, backgroundColor: colors.indigo, opacity: 0.7, alignSelf: "stretch" },
  jarvisText: { color: colors.text, fontSize: 16.5, lineHeight: 25, fontFamily: font.family },
  inlineCode: { fontFamily: font.mono, fontSize: 14, color: colors.text, backgroundColor: colors.surface2 },
  codeBlock: { fontFamily: font.mono, fontSize: 13.5, lineHeight: 19, color: colors.text, backgroundColor: "#0B1020", borderRadius: radius.sm, padding: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2, overflow: "hidden" },
  link: { color: colors.cyan, textDecorationLine: "underline" },
  tag: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 7, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.surface },
  tagText: { color: colors.text3, fontSize: 11, fontWeight: "600", fontFamily: font.family },
  quickRow: { flexDirection: "row", gap: 8, marginTop: 10, marginLeft: 15 },
  quick: { paddingHorizontal: 18, height: 38, borderRadius: radius.pill, backgroundColor: colors.surface2, justifyContent: "center", borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2 },
  quickText: { color: colors.text, fontSize: 15, fontWeight: "600", fontFamily: font.family },
  activity: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12, paddingVertical: 9, paddingHorizontal: 12, borderRadius: radius.md, backgroundColor: colors.surface, alignSelf: "flex-start", maxWidth: "100%" },
  activityIcon: { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  activityText: { color: colors.text, fontSize: 14, flexShrink: 1, fontFamily: font.family },
  confirm: { marginTop: 14, padding: 16, borderRadius: radius.lg, backgroundColor: colors.surface, borderWidth: 1, borderColor: "rgba(125,157,255,0.35)", gap: 4 },
  confirmTitle: { color: colors.text, fontSize: 16.5, fontWeight: "650" as any, fontFamily: font.family },
  confirmDetail: { color: colors.text2, fontSize: 14.5, fontFamily: font.family },
  confirmRow: { flexDirection: "row", gap: 10, marginTop: 12 },
  confirmDone: { marginTop: 6, fontSize: 13.5, fontWeight: "600" },
  btn: { flex: 1, height: 46, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  btnPrimary: { backgroundColor: colors.text },
  btnPrimaryText: { color: colors.bg, fontSize: 16, fontWeight: "700", fontFamily: font.family },
  btnQuiet: { backgroundColor: colors.surface2 },
  btnQuietText: { color: colors.text, fontSize: 16, fontWeight: "600", fontFamily: font.family },
  note: { alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 14, paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: "rgba(255,255,255,0.04)", maxWidth: "92%" },
  noteErr: { backgroundColor: "rgba(255,107,129,0.08)" },
  noteText: { color: colors.text3, fontSize: 13, textAlign: "center", fontFamily: font.family },
  thinking: { flexDirection: "row", alignItems: "center", gap: 13, marginTop: 14, height: 28 },
  dots: { flexDirection: "row", gap: 5 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  thinkingText: { color: colors.text3, fontSize: 13, fontFamily: font.family },
  empty: { paddingBottom: 6, gap: 10 },
  emptyTitle: { color: colors.text, fontSize: 29, lineHeight: 34, fontWeight: "700", letterSpacing: -0.6, marginTop: 10, fontFamily: font.family },
  emptySub: { color: colors.text2, fontSize: 15.5, lineHeight: 22, marginBottom: 12, fontFamily: font.family },
  suggestions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  suggestion: { width: "48.6%", flexGrow: 1, padding: 14, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2, gap: 3, minHeight: 72 },
  suggestionTitle: { color: colors.text, fontSize: 14.5, fontWeight: "650" as any, fontFamily: font.family },
  suggestionText: { color: colors.text3, fontSize: 13, lineHeight: 17, fontFamily: font.family },
  credit: { color: colors.text3, fontSize: 12, marginTop: 6, fontFamily: font.family },
  composerWrap: { paddingTop: 8, paddingHorizontal: 10, backgroundColor: colors.bg },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  field: { flex: 1, minHeight: 50, borderRadius: 25, backgroundColor: colors.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line2, justifyContent: "center", paddingHorizontal: 18, paddingVertical: 13 },
  fieldRec: { backgroundColor: colors.surface2 },
  input: { color: colors.text, fontSize: 16, lineHeight: 22, padding: 0, margin: 0, fontFamily: font.family, textAlignVertical: "top" },
  recBar: { flexDirection: "row", alignItems: "center", gap: 10, height: 22 },
  recDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: colors.red },
  recTime: { color: colors.text, fontSize: 15, fontWeight: "600", fontVariant: ["tabular-nums"] },
  recHint: { color: colors.text3, fontSize: 14, flex: 1, fontFamily: font.family },
  recCancel: { color: colors.red, fontSize: 14, fontWeight: "600" },
  action: { width: 50, height: 50, borderRadius: 25, backgroundColor: colors.surface2, alignItems: "center", justifyContent: "center" },
  actionSend: { backgroundColor: colors.text },
  actionRec: { backgroundColor: colors.red },
});
