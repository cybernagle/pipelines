# Copyright 2023 The Kubeflow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Python function-based components used in KFP pipelies."""
import functools
from typing import List, NamedTuple, Optional

from google_cloud_pipeline_components import _image
from google_cloud_pipeline_components._implementation.llm import env
from kfp import dsl


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_machine_spec(
    location: str,
    use_test_spec: bool = False,
) -> NamedTuple(
    'MachineSpec', machine_type=str, accelerator_type=str, accelerator_count=int
):
  """Returns machine spec to use for a given location.

  Args:
    location: Where the machine will run.
    use_test_spec: Whether to use a lower resource machine for testing.

  Returns:
    Machine spec.

  Raises:
    ValueError: If accelerators are requested in an unsupported location.
  """
  outputs = NamedTuple(
      'MachineSpec',
      machine_type=str,
      accelerator_type=str,
      accelerator_count=int,
  )
  tpu_regions = {'europe-west4'}
  gpu_regions = {'us-central1'}
  if use_test_spec:
    return outputs(
        machine_type='a2-highgpu-1g',
        accelerator_type='NVIDIA_TESLA_A100',
        accelerator_count=1,
    )
  elif location in tpu_regions:
    return outputs(
        machine_type='cloud-tpu',
        accelerator_type='TPU_V3',
        accelerator_count=64,
    )
  elif location in gpu_regions:
    return outputs(
        machine_type='a2-ultragpu-8g',
        accelerator_type='NVIDIA_A100_80GB',
        accelerator_count=8,
    )
  raise ValueError(
      f'Unsupported accelerator location {location}. Must be one of'
      f' {tpu_regions | gpu_regions}.'
  )


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_image_uri(
    image_name: str,
    project: str,
    location: str,
    artifact_registry: str,
    image_name_prefix: str,
    tag: str,
    accelerator_type: str = '',
    accelerator_count: int = 0,
) -> str:
  """Generates image uri based on base image name and accelerator type.

  Args:
    image_name: Base image name, e.g. ``'sft'`` or ``'reward_model'``.
    project: Project that contains the artifact registry.
    location: Region that contains the artifact registry.
    artifact_registry: Registry that contains Docker images.
    image_name_prefix: Text to prepend to the base image name.
    tag: Image tag.
    accelerator_type: One of the supported accelerator types, e.g. ``'TPU_V3'``.
    accelerator_count: Number of accelerators.

  Returns:
    Docker image uri

  Raises:
    ValueError: if an unsupported accelerator type is provided.
  """
  cpu_only_images = {
      'text_importer',
      'text_comparison_importer',
  }

  if image_name in cpu_only_images:
    accelerator_postfix = ''
  elif accelerator_type == 'TPU_V3':
    accelerator_postfix = '_tpu'
  elif accelerator_type == 'NVIDIA_A100_80GB' and accelerator_count == 8:
    accelerator_postfix = '_gpu_test'
  else:
    accelerator_postfix = '_gpu'

  backup_images = {
      'sft',
      'reward_model',
      'reinforcer',
      'infer',
      'text_importer',
      'text_comparison_importer',
  }
  if image_name in backup_images and accelerator_postfix != '_gpu_test':
    accelerator_postfix += '_backup'
  return f'{location}-docker.pkg.dev/{project}/{artifact_registry}/{image_name_prefix}{image_name}{accelerator_postfix}:{tag}'


# Resolves image uri from the environment's private artifact registry.
# By default this resolves an image in the vertex private registry.
resolve_private_image_uri = functools.partial(
    resolve_image_uri,
    project=env.PRIVATE_ARTIFACT_REGISTRY_PROJECT,
    location=env.PRIVATE_ARTIFACT_REGISTRY_LOCATION,
    artifact_registry=env.PRIVATE_ARTIFACT_REGISTRY,
    image_name_prefix=env.PRIVATE_IMAGE_NAME_PREFIX,
    tag=env.get_private_image_tag(),
)


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_data_paths(
    input_dataset: str,
) -> NamedTuple('DataPaths', tfds_data_dir=str, tfds_name=str):
  """Resolves dataset paths needed by downstream components."""
  # pylint: disable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported
  import os
  # pylint: enable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported
  outputs = NamedTuple('DataPaths', tfds_data_dir=str, tfds_name=str)
  tfds_data_dir, tfds_name = os.path.split(input_dataset)
  return outputs(
      tfds_data_dir=tfds_data_dir,
      tfds_name=tfds_name,
  )


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_reference_model_metadata(
    large_model_reference: str,
    reference_model_path: Optional[str] = None,
) -> NamedTuple(
    'Outputs',
    large_model_reference=str,
    reference_model_path=str,
    reward_model_reference=str,
    reward_model_path=str,
):
  """Resolves reference model metadata needed by downstream components.

  Args:
    large_model_reference: User-provided reference model name.
    reference_model_path: Optional path to a tuned based model to use in place
      of the default base model. If specified, the model at this path must be a
      tuned version of the base model associated with ``large_model_reference``.

  Returns:
    Base model name (used by downstream components to find gin configs and load
    vocabularies) and the path to the base model checkpoint.

  Raises:
    ValueError: if no metadata exists for the given base model.
  """
  reference_model_metadata = NamedTuple(
      'ReferenceModelMetadata',
      large_model_reference=str,
      reference_model_path=str,
      reward_model_reference=str,
      reward_model_path=str,
      is_supported=bool,
  )

  reference_models = {
      't5-small': reference_model_metadata(
          large_model_reference='T5_SMALL',
          reference_model_path=(
              'gs://t5-data/pretrained_models/t5x/flan_t5_small/'
          ),
          reward_model_reference='T5_SMALL',
          reward_model_path='gs://t5-data/pretrained_models/t5x/t5_1_1_small',
          is_supported=True,
      ),
      't5-large': reference_model_metadata(
          large_model_reference='T5_LARGE',
          reference_model_path=(
              'gs://t5-data/pretrained_models/t5x/flan_t5_large/'
          ),
          reward_model_reference='T5_LARGE',
          reward_model_path='gs://t5-data/pretrained_models/t5x/t5_1_1_large',
          is_supported=True,
      ),
      't5-xl': reference_model_metadata(
          large_model_reference='T5_XL',
          reference_model_path='gs://t5-data/pretrained_models/t5x/flan_t5_xl/',
          reward_model_reference='T5_XL',
          reward_model_path='gs://t5-data/pretrained_models/t5x/t5_1_1_xl',
          is_supported=True,
      ),
      't5-xxl': reference_model_metadata(
          large_model_reference='T5_XXL',
          reference_model_path=(
              'gs://t5-data/pretrained_models/t5x/flan_t5_xxl/'
          ),
          reward_model_reference='T5_XL',
          reward_model_path='gs://t5-data/pretrained_models/t5x/t5_1_1_xl',
          is_supported=True,
      ),
      'palm-tiny': reference_model_metadata(
          large_model_reference='PALM_TINY',
          reference_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_palm_tiny/',
          reward_model_reference='PALM_TINY',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_palm_tiny/',
          is_supported=False,
      ),
      'gecko': reference_model_metadata(
          large_model_reference='GECKO',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_gecko/'
          ),
          reward_model_reference='GECKO',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_gecko_pretrain/',
          is_supported=False,
      ),
      'otter': reference_model_metadata(
          large_model_reference='OTTER',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter/'
          ),
          reward_model_reference='OTTER',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter_pretrain/',
          is_supported=False,
      ),
      'bison': reference_model_metadata(
          large_model_reference='BISON',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_bison/'
          ),
          reward_model_reference='OTTER',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter_pretrain/',
          is_supported=False,  # Deprecated: Use text-bision@001 instead.
      ),
      'text-bison@001': reference_model_metadata(
          large_model_reference='BISON',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_bison/'
          ),
          reward_model_reference='OTTER',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter_pretrain/',
          is_supported=True,
      ),
      'chat-bison@001': reference_model_metadata(
          large_model_reference='BISON',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_bison/'
          ),
          reward_model_reference='OTTER',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter_pretrain/',
          is_supported=True,
      ),
      'elephant': reference_model_metadata(
          large_model_reference='ELEPHANT',
          reference_model_path=(
              'gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_elephant/'
          ),
          reward_model_reference='OTTER',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/palm/t5x_otter_pretrain/',
          is_supported=False,
      ),
      'llama-2-7b': reference_model_metadata(
          large_model_reference='LLAMA_2_7B',
          reference_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_7b/',
          reward_model_reference='LLAMA_2_7B',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_7b/',
          is_supported=True,
      ),
      'llama-2-13b': reference_model_metadata(
          large_model_reference='LLAMA_2_13B',
          reference_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_13b/',
          reward_model_reference='LLAMA_2_13B',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_13b/',
          is_supported=True,
      ),
      'llama-2-7b-chat': reference_model_metadata(
          large_model_reference='LLAMA_2_7B_CHAT',
          reference_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_7b_chat/',
          reward_model_reference='LLAMA_2_7B',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_7b/',
          is_supported=True,
      ),
      'llama-2-13b-chat': reference_model_metadata(
          large_model_reference='LLAMA_2_13B_CHAT',
          reference_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_13b_chat/',
          reward_model_reference='LLAMA_2_13B',
          reward_model_path='gs://vertex-rlhf-restricted/pretrained_models/llama/t5x_llama_2_13b/',
          is_supported=True,
      ),
  }

  reference_model_key = large_model_reference.lower().replace('_', '-')
  if reference_model_key not in reference_models:
    supported_models = [
        k for k, v in reference_models.items() if v.is_supported
    ]
    raise ValueError(
        f'Unknown reference model {large_model_reference}.'
        ' large_model_reference must be one of'
        f' {sorted(supported_models)}.'
    )

  reference_model = reference_models[reference_model_key]

  outputs = NamedTuple(
      'Outputs',
      large_model_reference=str,
      reference_model_path=str,
      reward_model_reference=str,
      reward_model_path=str,
  )

  return outputs(
      large_model_reference=reference_model.large_model_reference,
      reference_model_path=(
          reference_model_path or reference_model.reference_model_path
      ),
      reward_model_reference=reference_model.reward_model_reference,
      reward_model_path=reference_model.reward_model_path,
  )


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def convert_to_delimited_string(items: List[str], delimiter: str = ',') -> str:
  """Converts a list of strings to single string delimited by the specified character."""
  return delimiter.join(items)


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def generate_default_instruction(
    task: str,
    target_sequence_length: int,
    instruction_override: str = '',
) -> str:
  """Generates a default instruction if no override is provided."""
  if instruction_override:
    return instruction_override
  task = task.lower()
  if task == 'summarization':
    return f'Summarize in less than {target_sequence_length} words.'

  elif task == 'question_answer':
    return f'Answer the question in less than {target_sequence_length} words.'

  else:
    raise ValueError(
        f'Task not recognized: {task}. Supported tasks are: "summarization",'
        ' "question_answer".'
    )


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_upload_location(upload_location: Optional[str] = None) -> str:
  """Gets the region to upload the model.

  Args:
    upload_location: User-specified region to upload the model to.

  Returns:
    Where to upload the model. If no location is specified, the model will be
    uploaded to the region where the pipeline is running.
  """
  # pylint: disable=g-import-not-at-top
  import os
  # pylint: enable=g-import-not-at-top
  return upload_location or os.environ['CLOUD_ML_REGION']


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_regional_endpoint(upload_location: str) -> str:
  """Gets the regional endpoint used to upload a model to the registry.

  Args:
    upload_location: Region where the model will be uploaded.

  Returns:
    Regional endpoint.
  """
  return f'https://{upload_location}-aiplatform.googleapis.com/ui'


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_model_display_name(
    large_model_reference: str,
    model_display_name: Optional[str] = None,
) -> str:
  """Gets the model display name shown in the registry and used for endpoints.

  Args:
    large_model_reference: Base model tuned by the pipeline.
    model_display_name: User-provided display name. If not provided, a default
      display name will be created.

  Returns:
    Either the user-provided name or a default display name with the form
    ``{large_model_reference}-{timestamp}``
  """
  # pylint: disable=g-import-not-at-top
  import datetime
  # pylint: enable=g-import-not-at-top
  now = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
  return model_display_name or f'{large_model_reference.lower()}-{now}'


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_deploy_model(
    deploy_model: bool, large_model_reference: str
) -> bool:
  """Resolves runtime parameter that determines whether the tuned model should be deployed."""
  supported_models = {'BISON'}
  if deploy_model and large_model_reference in supported_models:
    return True
  return False


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def value_exists(value: Optional[str] = None) -> bool:
  """Returns whether a runtime parameter was provided.

  Args:
    value: That might have been provided.

  Returns:
    Whether the string is not None and non-empty.
  """
  if not value:
    return False
  return True


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_candidate_columns(
    candidate_columns: Optional[List[str]] = None,
) -> List[str]:
  """Returns candidate columns provided by the user or the default: ['candidate_0', 'candidate_1']."""
  return candidate_columns or ['candidate_0', 'candidate_1']


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_upload_model(large_model_reference: str) -> bool:
  """Returns whether the model should be uploaded."""
  supported_models = {'BISON'}
  if large_model_reference in supported_models:
    return True
  return False


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def resolve_instruction(
    large_model_reference: str, instruction: Optional[str] = None
) -> str:
  """Resolves the instruction to use for a given reference model.

  Args:
    large_model_reference: Base model tuned by the pipeline.
    instruction: Instruction provided at runtime.

  Returns:
    Instruction to use during tokenization based on model type. Returns an empty
      string for chat models because the instruction is prepended as the default
      context. Otherwise the original instruction is returned.
  """
  instruction = instruction or ''
  return instruction if 'chat' not in large_model_reference.lower() else ''


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def identity(value: str) -> str:
  """Returns the input value."""
  return value


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def get_default_bulk_inference_machine_specs(
    large_model_reference: str,
    use_gpu_defaults: bool = False,
    accelerator_type_override: Optional[str] = None,
    accelerator_count_override: Optional[int] = None,
) -> NamedTuple(
    'MachineSpec', accelerator_type=str, accelerator_count=int, machine_type=str
):
  """Gets default machine specs for bulk inference and overrides params if provided.

  Args:
    large_model_reference: Foundational model to use for default specs.
    use_gpu_defaults: Whether to get default gpu specs (otherwise will get TPU
      specs).
    accelerator_type_override: Accelerator type to override the default.
    accelerator_count_override: Accelerator count to override the default.

  Returns:
    MachineSpec, including accelerator_type, accelerator_count, machine_type.

  Raises:
    ValueError: If large_model_reference is invalid or overridden values are
    invalid.
  """
  machine_spec = NamedTuple(
      'MachineSpec',
      accelerator_type=str,
      accelerator_count=int,
      machine_type=str,
  )

  # machine types
  cloud_tpu = 'cloud-tpu'
  ultra_gpu_1g = 'a2-ultragpu-1g'
  ultra_gpu_2g = 'a2-ultragpu-2g'
  ultra_gpu_4g = 'a2-ultragpu-4g'
  ultra_gpu_8g = 'a2-ultragpu-8g'
  high_gpu_1g = 'a2-highgpu-1g'
  high_gpu_2g = 'a2-highgpu-2g'
  high_gpu_4g = 'a2-highgpu-4g'
  high_gpu_8g = 'a2-highgpu-8g'
  mega_gpu_16g = 'a2-megagpu-16g'

  # accelerator types
  tpu_v2 = 'TPU_V2'
  tpu_v3 = 'TPU_V3'
  nvidia_a100_40g = 'NVIDIA_TESLA_A100'
  nvidia_a100_80g = 'NVIDIA_A100_80GB'
  tpu_accelerator_types = frozenset([tpu_v2, tpu_v3])
  gpu_accelerator_types = frozenset([nvidia_a100_40g, nvidia_a100_80g])
  valid_accelerator_types = gpu_accelerator_types | tpu_accelerator_types

  # base models
  palm_tiny = 'PALM_TINY'
  gecko = 'GECKO'
  otter = 'OTTER'
  bison = 'BISON'
  elephant = 'ELEPHANT'
  t5_small = 'T5_SMALL'
  t5_large = 'T5_LARGE'
  t5_xl = 'T5_XL'
  t5_xxl = 'T5_XXL'

  def _get_machine_type(accelerator_type: str, accelerator_count: int) -> str:
    if accelerator_count < 1:
      raise ValueError('accelerator_count must be at least 1.')

    if accelerator_type in tpu_accelerator_types:
      return cloud_tpu

    elif accelerator_type == nvidia_a100_40g:
      if accelerator_count == 1:
        return high_gpu_1g

      elif accelerator_count == 2:
        return high_gpu_2g

      elif accelerator_count <= 4:
        return high_gpu_4g

      elif accelerator_count <= 8:
        return high_gpu_8g

      elif accelerator_count <= 16:
        return mega_gpu_16g

      else:
        raise ValueError(
            f'Too many {accelerator_type} requested. Must be <= 16.'
        )

    elif accelerator_type == nvidia_a100_80g:
      if accelerator_count == 1:
        return ultra_gpu_1g

      elif accelerator_count == 2:
        return ultra_gpu_2g

      elif accelerator_count <= 4:
        return ultra_gpu_4g

      elif accelerator_count <= 8:
        return ultra_gpu_8g

      else:
        raise ValueError(
            f'Too many {accelerator_type} requested. Must be <= 8.'
        )

    else:
      raise ValueError(
          'accelerator_type_override must be one of'
          f' {sorted(valid_accelerator_types)}.'
      )

  accepted_reference_models = frozenset([
      palm_tiny,
      gecko,
      otter,
      bison,
      elephant,
      t5_small,
      t5_large,
      t5_xl,
      t5_xxl,
  ])

  # Default GPU specs are based on study here:
  # https://docs.google.com/spreadsheets/d/1_ZKqfyLQ5vYrOQH5kfdMb_OoNT48r6vNbqv3dKDxDTw/edit?resourcekey=0-3kgDrn4XDdvlJAc8Kils-Q#gid=255356424
  reference_model_to_model_specs_gpu = {
      palm_tiny: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=1,
          machine_type=high_gpu_1g,
      ),
      gecko: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=1,
          machine_type=high_gpu_1g,
      ),
      otter: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=2,
          machine_type=high_gpu_2g,
      ),
      bison: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=8,
          machine_type=high_gpu_8g,
      ),
      elephant: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=8,
          machine_type=high_gpu_8g,
      ),
      t5_small: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=1,
          machine_type=high_gpu_1g,
      ),
      t5_large: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=1,
          machine_type=high_gpu_1g,
      ),
      t5_xl: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=1,
          machine_type=high_gpu_1g,
      ),
      t5_xxl: machine_spec(
          accelerator_type=nvidia_a100_40g,
          accelerator_count=2,
          machine_type=high_gpu_2g,
      ),
  }

  # Get defaults
  if large_model_reference not in accepted_reference_models:
    # List of models that show up in the user-facing error message:
    raise ValueError(
        'large_model_reference must be one of'
        f' {sorted(accepted_reference_models)}.'
    )

  if use_gpu_defaults:
    default_machine_spec = reference_model_to_model_specs_gpu[
        large_model_reference
    ]

  else:
    # Only v3 TPU Pods are available in the shared pool, so this count must be
    # >= 32.
    default_machine_spec = machine_spec(
        accelerator_type=tpu_v3,
        accelerator_count=32,
        machine_type=cloud_tpu,
    )

  # Override default behavior we defer validations of these to the resource
  # provisioner.
  if any([accelerator_type_override, accelerator_count_override]):
    if not all([accelerator_type_override, accelerator_count_override]):
      raise ValueError('Accelerator type and count must both be set.')
    accelerator_type = accelerator_type_override
    accelerator_count = accelerator_count_override
  else:
    accelerator_type = default_machine_spec.accelerator_type
    accelerator_count = default_machine_spec.accelerator_count

  return machine_spec(
      accelerator_type=accelerator_type,
      accelerator_count=accelerator_count,
      machine_type=_get_machine_type(accelerator_type, accelerator_count),
  )


@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def write_file(path: str, content: str):
  """Writes the contents to the given file."""
  # pylint: disable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported
  import re
  import os
  # pylint: enable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported

  path = re.sub('^gs://', '/gcs/', path)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, 'w') as f:
    f.write(content)


# TODO: b/245451217 - Remove read/write/identity components once fan-in
# conditions are supported
@dsl.component(base_image=_image.GCPC_IMAGE_TAG, install_kfp_package=False)
def read_file(path: str) -> str:
  """Reads the contents of the given file."""
  # pylint: disable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported
  import re
  # pylint: enable=g-import-not-at-top,import-outside-toplevel,redefined-outer-name,reimported

  path = re.sub('^gs://', '/gcs/', path)
  with open(path, 'r') as f:
    return f.read()
