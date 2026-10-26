"""Explicit, fixed command/physics timing for the proposed numerical repair."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationContract:
    timestep: float = .0025
    command_period: float = .02
    contact_reference_timestep: float = .005

    def __post_init__(self):
        if self.timestep not in (.005,.0025) or self.command_period!=.02 or self.contact_reference_timestep!=.005:
            raise ValueError('unsupported_integration_contract')

    @property
    def substeps(self):
        return round(self.command_period/self.timestep)

    def command_index(self,physics_step):
        if type(physics_step) is not int or physics_step<0:raise ValueError('invalid_physics_index')
        return physics_step//self.substeps

    def first_step(self,command_index):
        if type(command_index) is not int or command_index<0:raise ValueError('invalid_command_index')
        return command_index*self.substeps

    def reserve(self,commands):
        return dict(task_and_replay_steps=commands*self.substeps*2,wbc_and_recompute=commands*2)
