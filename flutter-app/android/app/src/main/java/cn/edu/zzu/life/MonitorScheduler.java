package cn.edu.zzu.life;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

final class MonitorScheduler {
    private static final String CHANNEL_ID = "zzu_life_monitoring";
    private static final int ALARM_REQUEST = 8102;
    private static final long HOUR = 60L * 60L * 1000L;

    private MonitorScheduler() {}

    static void reschedule(Context context) {
        AlarmManager alarm = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        PendingIntent intent = alarmIntent(context);
        alarm.cancel(intent);
        if (!MonitorSettings.energyEnabled(context) && !MonitorSettings.gradeEnabled(context)) return;

        long minutes = MonitorSettings.gradeEnabled(context)
            ? MonitorSettings.gradeIntervalMinutes(context)
            : 24 * 60L;
        if (MonitorSettings.energyEnabled(context)) minutes = Math.min(minutes, 6 * 60L);
        long interval = Math.max(15L * 60L * 1000L, minutes * 60L * 1000L);
        alarm.setInexactRepeating(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + Math.min(interval, 5 * 60L * 1000L),
            interval,
            intent
        );
    }

    static JSONObject check(Context context, boolean grades, boolean energy, boolean notify) {
        JSONObject result = new JSONObject();
        try {
            result.put("ok", true);
            String[] stored = SessionStore.load(context);
            if (stored == null) {
                result.put("message", "登录已失效，请打开应用重新登录");
                return result;
            }
            PythonGateway.ContextSession session = new PythonGateway.ContextSession(stored);
            if (grades) checkGrades(context, session, notify, result);
            if (energy) checkEnergy(context, session, notify, result);
            if (!result.has("message")) result.put("message", "检查完成");
        } catch (Exception error) {
            try {
                result.put("ok", true);
                result.put("message", error.getMessage() == null ? "检查失败" : error.getMessage());
            } catch (Exception ignored) {}
        }
        return result;
    }

    private static void checkGrades(
        Context context,
        PythonGateway.ContextSession session,
        boolean notify,
        JSONObject output
    ) throws Exception {
        JSONObject payload = PythonGateway.callWithSession(session, "get_grades");
        if (!payload.optBoolean("ok")) throw new IllegalStateException(payload.optString("error", "成绩查询失败"));
        JSONArray grades = payload.optJSONArray("grades");
        if (grades == null) grades = new JSONArray();
        JSONObject current = new JSONObject();
        for (int i = 0; i < grades.length(); i++) {
            JSONObject item = grades.optJSONObject(i);
            if (item == null) continue;
            String key = item.optString("semester") + "\u0001" + item.optString("course");
            String value = item.optString("score") + "\u0001" + item.optString("gp");
            current.put(key, value);
        }

        String previousRaw = MonitorSettings.gradeSnapshot(context);
        int changed = 0;
        if (!previousRaw.isEmpty()) {
            JSONObject previous = new JSONObject(previousRaw);
            JSONArray keys = current.names();
            if (keys != null) {
                for (int i = 0; i < keys.length(); i++) {
                    String key = keys.getString(i);
                    if (!previous.has(key) || !current.optString(key).equals(previous.optString(key))) changed++;
                }
            }
        }
        MonitorSettings.saveGradeSnapshot(context, current.toString());
        String now = new SimpleDateFormat("MM-dd HH:mm", Locale.CHINA).format(new Date());
        String message;
        if (previousRaw.isEmpty()) {
            message = "已建立监测基准，共 " + current.length() + " 门课程";
        } else if (changed > 0) {
            message = "发现 " + changed + " 门课程成绩更新";
            if (notify) notify(context, 2101, "成绩有更新", message);
        } else {
            message = "暂未发现新成绩";
        }
        MonitorSettings.setGradeStatus(context, now, message);
        output.put("new_grades", changed);
        output.put("message", message);
    }

    private static void checkEnergy(
        Context context,
        PythonGateway.ContextSession session,
        boolean notify,
        JSONObject output
    ) throws Exception {
        JSONObject payload = PythonGateway.callWithSession(session, "get_energy");
        if (!payload.optBoolean("ok")) throw new IllegalStateException(payload.optString("error", "电量查询失败"));
        JSONArray meters = payload.optJSONArray("meter_list");
        if (meters == null) return;
        double threshold = MonitorSettings.energyThreshold(context);
        String lowLabel = "";
        double lowest = Double.MAX_VALUE;
        for (int i = 0; i < meters.length(); i++) {
            JSONObject meter = meters.optJSONObject(i);
            if (meter == null || meter.has("error")) continue;
            double remaining = meter.optDouble("remaining", Double.NaN);
            if (!Double.isNaN(remaining) && remaining <= threshold && remaining < lowest) {
                lowest = remaining;
                lowLabel = meter.optString("label", "寝室电表");
            }
        }
        boolean low = !lowLabel.isEmpty();
        if (low && !MonitorSettings.energyAlerted(context)) {
            if (notify) {
                notify(
                    context,
                    2102,
                    "寝室电量偏低",
                    lowLabel + "剩余 " + String.format(Locale.CHINA, "%.2f", lowest) + " 度"
                );
            }
            MonitorSettings.setEnergyAlerted(context, true);
        } else if (!low) {
            MonitorSettings.setEnergyAlerted(context, false);
        }
        output.put("energy_low", low);
    }

    private static void notify(Context context, int id, String title, String text) {
        if (Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "成绩与电量提醒",
            NotificationManager.IMPORTANCE_DEFAULT
        );
        manager.createNotificationChannel(channel);
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent content = PendingIntent.getActivity(
            context,
            id,
            open,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification notification = new Notification.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher_v6)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(content)
            .setAutoCancel(true)
            .build();
        manager.notify(id, notification);
    }

    private static PendingIntent alarmIntent(Context context) {
        return PendingIntent.getBroadcast(
            context,
            ALARM_REQUEST,
            new Intent(context, MonitorReceiver.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }
}
