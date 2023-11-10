# Copyright 2021 The Kubeflow Authors. All Rights Reserved.
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
"""Remote runner for Get Model based on the AI Platform SDK."""

import logging

# from google.api_core import gapic_v1
# from google.cloud import aiplatform
from google.cloud import aiplatform_v1 as aip_v1
from google_cloud_pipeline_components.container.utils import artifact_utils
from google_cloud_pipeline_components.proto import gcp_resources_pb2
from google_cloud_pipeline_components.types import artifact_types

from google.protobuf import json_format


RESOURCE_TYPE = 'Model'


def get_model(
    executor_input,
    gcp_resources,
    model_name: str,
    project: str,
    location: str,
):
  """Get model."""
  api_endpoint = location + '-aiplatform.googleapis.com'
  vertex_uri_prefix = f'https://{api_endpoint}/v1/'
  model_resource_name = (
      f'projects/{project}/locations/{location}/models/{model_name}'
  )

  if not location or not project:
    raise ValueError(
        'Model resource name must be in the format'
        ' projects/{project}/locations/{location}/models/{model} or'
        ' projects/{project}/locations/{location}/models/{model}@{model_version}'
    )

  # client = aiplatform.gapic.ModelServiceClient(
  #     client_info=gapic_v1.client_info.ClientInfo(
  #         user_agent='google-cloud-pipeline-components'
  #     ),
  # client_options={
  #     'api_endpoint': api_endpoint,
  # },
  # )
  client = aip_v1.ModelServiceClient(
      client_options={
          'api_endpoint': api_endpoint,
      },
  )
  request = aip_v1.GetModelRequest(name=model_resource_name)
  logging.info('the request is: ')
  logging.info(request)

  get_model_response = client.get_model(request)
  logging.info('the response is: ')
  logging.info(get_model_response)

  resp_model_name_without_version = get_model_response.name.split('@', 1)[0]
  model_resource_name = (
      f'{resp_model_name_without_version}@{get_model_response.version_id}'
  )

  vertex_model = artifact_types.VertexModel.create(
      'model', vertex_uri_prefix + model_resource_name, model_resource_name
  )
  # TODO(b/266848949): Output Artifact should use correct MLMD artifact.
  artifact_utils.update_output_artifacts(executor_input, [vertex_model])

  resources = gcp_resources_pb2.GcpResources()
  model_resource = resources.resources.add()
  model_resource.resource_type = RESOURCE_TYPE
  model_resource.resource_uri = f'{vertex_uri_prefix}{model_resource_name}'
  with open(gcp_resources, 'w') as f:
    f.write(json_format.MessageToJson(resources))
