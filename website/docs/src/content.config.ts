import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// English-only site. If you add translations later, also declare an `i18n`
// collection here and create `src/content/i18n/`.
export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
