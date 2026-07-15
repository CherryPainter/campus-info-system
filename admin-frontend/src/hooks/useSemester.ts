import { useState, useEffect, useCallback } from 'react';
import { courseApi } from '@/api/course';
import type { SemesterInfo } from '@/api/course';

/**
 * 学期列表 Hook（Course 与 CrawlScheduler 共用）
 * 自动请求学期列表，并默认选中 is_current 的项。
 */
export function useSemester() {
  const [semesters, setSemesters] = useState<SemesterInfo[]>([]);
  const [selectedSemester, setSelectedSemester] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  const fetchSemesters = useCallback(async () => {
    setLoading(true);
    try {
      const res = await courseApi.getSemesters();
      if (res.status === 'success' && res.data) {
        const semestersData = res.data.semesters || [];
        const currentId = res.data.current_semester_id;
        const list: SemesterInfo[] = semestersData.map((s: any) => ({
          id: parseInt(s.id) || 0,
          name: s.name,
          is_current: String(s.id) === String(currentId),
          eams_id: s.eams_id,
        }));
        setSemesters(list);
        const current = list.find((s) => s.is_current);
        if (current) setSelectedSemester(current.id);
      }
    } catch (error) {
      console.error('获取学期列表失败:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSemesters();
  }, [fetchSemesters]);

  const currentSemesterId = semesters.find((s) => s.is_current)?.id;

  return { semesters, currentSemesterId, selectedSemester, setSelectedSemester, loading };
}
