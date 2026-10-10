"""每周小数学时的离线回归测试：python -m unittest discover -s scripts -p test_fractional_periods.py。"""

import unittest

from icalendar import Calendar
from pydantic import ValidationError

from zzupy.model.eas import Lesson, LessonModel, PeriodInfo, TeachingWeek


class FractionalPeriodsTests(unittest.TestCase):
    def test_preserves_fractional_and_existing_values(self):
        for value in (0, 2, 2.5, 1.75, "2.5"):
            with self.subTest(value=value):
                parsed = PeriodInfo.model_validate({"periodsPerWeek": value})
                self.assertEqual(parsed.periods_per_week, float(value))
        self.assertEqual(PeriodInfo().periods_per_week, 0)
        self.assertEqual(PeriodInfo(periods_per_week=2.5).periods_per_week, 2.5)

    def test_invalid_text_is_not_silently_converted(self):
        with self.assertRaises(ValidationError):
            PeriodInfo.model_validate({"periodsPerWeek": "invalid"})

    def test_sixth_course_and_calendar_export(self):
        records = [
            {
                "course": {
                    "nameZh": f"Course {index}",
                    "periodInfo": {"periodsPerWeek": 2.5 if index == 5 else 2},
                },
                "schedules": [{
                    "date": "2026-08-31",
                    "weekday": 1,
                    "startTime": "08:00",
                    "endTime": "09:40",
                    "startUnit": 1,
                    "endUnit": 2,
                    "weekIndex": 1,
                }],
            }
            for index in range(6)
        ]
        result = LessonModel.model_validate({"data": records})
        self.assertEqual(len(result.data), 6)
        course = result.data[5]
        self.assertEqual(course.course.period_info.periods_per_week, 2.5)
        week = TeachingWeek()
        lesson = Lesson(course=course.course, schedule=course.schedules[0])
        week.set(1, 1, lesson)
        week.set(1, 2, lesson)
        exported = Calendar.from_ical(week.to_calendar().to_ical())
        events = exported.walk("VEVENT")
        self.assertEqual(len(events), 1)
        self.assertEqual(str(events[0]["SUMMARY"]), "Course 5")


if __name__ == "__main__":
    unittest.main()
