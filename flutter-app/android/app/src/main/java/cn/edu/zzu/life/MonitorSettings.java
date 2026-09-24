package cn.edu.zzu.life;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.util.Map;

final class MonitorSettings {
    private static final String PREFS = "monitor_settings";
    private static final String ENERGY_ENABLED = "energy_enabled";
    private static final String ENERGY_THRESHOLD = "energy_threshold";
    private static final String GRADE_ENABLED = "grade_enabled";
    private static final String GRADE_INTERVAL = "grade_interval_hours";
    private static final String GRADE_INTERVAL_MINUTES = "grade_interval_minutes";
    private static final String GRADE_SNAPSHOT = "grade_snapshot";
    private static final String LAST_GRADE_CHECK = "last_grade_check";
    private static final String LAST_GRADE_MESSAGE = "last_grade_message";
    private static final String ENERGY_ALERTED = "energy_alerted";

    private MonitorSettings() {}

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static boolean energyEnabled(Context context) {
        return prefs(context).getBoolean(ENERGY_ENABLED, false);
    }

    static double energyThreshold(Context context) {
        return Double.longBitsToDouble(
            prefs(context).getLong(ENERGY_THRESHOLD, Double.doubleToRawLongBits(10.0))
        );
    }

    static boolean gradeEnabled(Context context) {
        return prefs(context).getBoolean(GRADE_ENABLED, false);
    }

    static int gradeIntervalMinutes(Context context) {
        SharedPreferences values = prefs(context);
        if (values.contains(GRADE_INTERVAL_MINUTES)) {
            return values.getInt(GRADE_INTERVAL_MINUTES, 720);
        }
        return values.getInt(GRADE_INTERVAL, 12) * 60;
    }

    static String gradeSnapshot(Context context) {
        return prefs(context).getString(GRADE_SNAPSHOT, "");
    }

    static void saveGradeSnapshot(Context context, String snapshot) {
        prefs(context).edit().putString(GRADE_SNAPSHOT, snapshot).apply();
    }

    static boolean energyAlerted(Context context) {
        return prefs(context).getBoolean(ENERGY_ALERTED, false);
    }

    static void setEnergyAlerted(Context context, boolean alerted) {
        prefs(context).edit().putBoolean(ENERGY_ALERTED, alerted).apply();
    }

    static void setGradeStatus(Context context, String time, String message) {
        prefs(context).edit()
            .putString(LAST_GRADE_CHECK, time)
            .putString(LAST_GRADE_MESSAGE, message)
            .apply();
    }

    static void update(Context context, Map<String, Object> values) {
        SharedPreferences.Editor editor = prefs(context).edit();
        if (values.containsKey(ENERGY_ENABLED)) {
            editor.putBoolean(ENERGY_ENABLED, bool(values.get(ENERGY_ENABLED)));
        }
        if (values.containsKey(ENERGY_THRESHOLD)) {
            editor.putLong(
                ENERGY_THRESHOLD,
                Double.doubleToRawLongBits(number(values.get(ENERGY_THRESHOLD), 10.0))
            );
            editor.putBoolean(ENERGY_ALERTED, false);
        }
        if (values.containsKey(GRADE_ENABLED)) {
            editor.putBoolean(GRADE_ENABLED, bool(values.get(GRADE_ENABLED)));
        }
        if (values.containsKey(GRADE_INTERVAL)) {
            int hours = (int) number(values.get(GRADE_INTERVAL), 12);
            editor.putInt(GRADE_INTERVAL, Math.max(1, Math.min(168, hours)));
        }
        if (values.containsKey(GRADE_INTERVAL_MINUTES)) {
            int minutes = (int) number(values.get(GRADE_INTERVAL_MINUTES), 720);
            editor.putInt(GRADE_INTERVAL_MINUTES, Math.max(15, Math.min(10080, minutes)));
        }
        editor.apply();
    }

    static JSONObject toJson(Context context) throws Exception {
        SharedPreferences values = prefs(context);
        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put(ENERGY_ENABLED, energyEnabled(context));
        result.put(ENERGY_THRESHOLD, energyThreshold(context));
        result.put(GRADE_ENABLED, gradeEnabled(context));
        result.put(GRADE_INTERVAL, Math.max(1, gradeIntervalMinutes(context) / 60));
        result.put(GRADE_INTERVAL_MINUTES, gradeIntervalMinutes(context));
        result.put("last_grade_check", values.getString(LAST_GRADE_CHECK, ""));
        result.put("last_grade_message", values.getString(LAST_GRADE_MESSAGE, "尚未检查"));
        return result;
    }

    private static boolean bool(Object value) {
        return value instanceof Boolean ? (Boolean) value : Boolean.parseBoolean(String.valueOf(value));
    }

    private static double number(Object value, double fallback) {
        if (value instanceof Number) return ((Number) value).doubleValue();
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception ignored) {
            return fallback;
        }
    }
}
