import { derived, writable } from 'svelte/store';

import { getReviewProject, getReviewProjects } from '../../lib/api.js';

export const projectsStore = writable([]);

function adaptProject(project) {
  const total = project.stats?.total ?? 0;
  const undecided = project.stats?.undecided ?? total;
  const decided = total - undecided;

  return {
    guid: project.guid,
    name: project.name,

    status: project.derived_status === 'completed' ? 'completed' : 'in_progress',

    seeds: project.collections_count ?? project.collection_ids?.length ?? 0,

    queueCount: project.queues_count ?? 0,
    progress: total > 0 ? decided / total : 0,
    closedAt: null,
  };
}

export async function loadProjects() {
  const projects = (await getReviewProjects()).map(adaptProject);
  projectsStore.set(projects);
}

function adaptStats(stats = {}) {
  const kept = stats.keep ?? stats.kept ?? 0;
  const removed = stats.remove ?? stats.removed ?? 0;
  const added = stats.add ?? stats.added ?? 0;
  const skipped = stats.skip ?? stats.skipped ?? 0;
  const total = stats.total ?? 0;
  const undecided = stats.undecided ?? total;
  const decided = Math.max(0, total - undecided);

  return {
    kept,
    removed,
    added,
    skipped,
    decided,
    undecided,
    total,
    progress: total > 0 ? decided / total : 0,
  };
}

export async function loadProject(projectGuid) {
  const data = await getReviewProject(projectGuid);
  const project = data.project;

  const seed =
    project.collection_names?.length > 0
      ? project.collection_names
      : (project.collection_ids ?? []).map((id) => `Collection ${id}`);

  return {
    guid: project.guid,
    name: project.name,
    seed,
    stats: adaptStats(data.stats),

    queues: (data.queues ?? []).map((queue, index) => {
      const queueGuid = queue.queue_guid ?? queue.guid;
      const queueNumber = (queue.queue_index ?? index) + 1;

      return {
        id: `Queue #${queueNumber}`,
        name: queue.name,
        guid: queueGuid,
        total: queue.stats?.total ?? 0,
        stats: adaptStats(queue.stats),
        url: `${window.location.origin}/demo/review-projects/${project.guid}/queues/${queueGuid}`,
      };
    }),

    editMetadata: project.edit_metadata,
    publishEnabled: data.publish_enabled,
    showVirtualQueueLinks: project.show_virtual_queue_links_on_reviewer_landing,
  };
}

export const inProgressProjects = derived(projectsStore, ($p) =>
  $p.filter((p) => p.status === 'in_progress')
);
export const completedProjects = derived(projectsStore, ($p) =>
  $p.filter((p) => p.status === 'completed')
);
