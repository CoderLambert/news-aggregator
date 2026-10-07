import { useMutation, useQueryClient } from '@tanstack/react-query'
import { blockNews } from '@/services/api'
import { newsKeys } from '@/services/newsQueries'

export function useBlockNews() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (newsId: number) => blockNews(newsId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: newsKeys.lists() })
    },
  })
}
