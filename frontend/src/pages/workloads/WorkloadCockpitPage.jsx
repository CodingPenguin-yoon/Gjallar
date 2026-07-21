import { WorkloadInventory } from '../../features/workloads/inventory'

export default function WorkloadCockpitPage({ currentUser, canMutate }) {
  return <WorkloadInventory currentUser={currentUser} canStartVms={canMutate} />
}
