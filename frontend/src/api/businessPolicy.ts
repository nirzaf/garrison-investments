import { useQuery } from '@tanstack/react-query';

import { apiClient } from './client';
import type { components } from './schema';

export function useBusinessPolicy() {
  return useQuery({
    queryKey: ['business-policy'],
    queryFn: async () => {
      const { data } = await apiClient.get<components['schemas']['BusinessPolicyResponse']>(
        '/finance/policy'
      );
      return data;
    }
  });
}

export function labelledAmount(amount: string, currency: string | null | undefined) {
  return currency ? `${currency} ${amount}` : amount;
}
