/*
 * Copyright (c) 2023 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.commons.server.handlers;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.airbyte.api.model.generated.ConnectorBuilderProjectIdWithWorkspaceId;
import io.airbyte.api.model.generated.ConnectorBuilderProjectWithWorkspaceId;
import io.airbyte.api.model.generated.ExistingConnectorBuilderProjectWithWorkspaceId;
import io.airbyte.commons.server.errors.IdNotFoundKnownException;
import io.airbyte.config.ConnectorBuilderProject;
import io.airbyte.config.persistence.ConfigRepository;
import jakarta.inject.Inject;
import jakarta.inject.Singleton;
import java.io.IOException;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Supplier;

@SuppressWarnings("PMD.AvoidCatchingNPE")
@Singleton
public class ConnectorBuilderProjectsHandler {

  private final ConfigRepository configRepository;
  private final Supplier<UUID> uuidSupplier;

  @Inject
  public ConnectorBuilderProjectsHandler(final ConfigRepository configRepository,
                                         final Supplier<UUID> uuidSupplier) {
    this.configRepository = configRepository;
    this.uuidSupplier = uuidSupplier;
  }

  // This should be deleted when cloud is migrated to micronaut
  @Deprecated(forRemoval = true)
  public ConnectorBuilderProjectsHandler(final ConfigRepository configRepository,
                                         final SourceHandler sourceHandler) {
    this.configRepository = configRepository;
    this.uuidSupplier = UUID::randomUUID;
  }

  private ConnectorBuilderProject builderProjectFromUpdate(final ExistingConnectorBuilderProjectWithWorkspaceId projectCreate) {
    return new ConnectorBuilderProject().withBuilderProjectId(projectCreate.getBuilderProjectId()).withWorkspaceId(projectCreate.getWorkspaceId())
        .withName(projectCreate.getBuilderProject().getName())
        .withManifestDraft(new ObjectMapper().valueToTree(projectCreate.getBuilderProject().getDraftManifest()));
  }

  private ConnectorBuilderProject builderProjectFromCreate(final ConnectorBuilderProjectWithWorkspaceId projectCreate) {
    final UUID id = uuidSupplier.get();

    return new ConnectorBuilderProject().withBuilderProjectId(id).withWorkspaceId(projectCreate.getWorkspaceId())
        .withName(projectCreate.getBuilderProject().getName())
        .withManifestDraft(new ObjectMapper().valueToTree(projectCreate.getBuilderProject().getDraftManifest()));
  }

  private ConnectorBuilderProjectIdWithWorkspaceId idResponseFromBuilderProject(final ConnectorBuilderProject project) {
    return new ConnectorBuilderProjectIdWithWorkspaceId().workspaceId(project.getWorkspaceId()).builderProjectId(project.getBuilderProjectId());
  }

  public ConnectorBuilderProjectIdWithWorkspaceId createConnectorBuilderProject(final ConnectorBuilderProjectWithWorkspaceId projectCreate)
      throws IOException {
    final ConnectorBuilderProject project = builderProjectFromCreate(projectCreate);

    configRepository.writeBuilderProject(project);

    return idResponseFromBuilderProject(project);
  }

  public void updateConnectorBuilderProject(final ExistingConnectorBuilderProjectWithWorkspaceId projectUpdate)
      throws IOException {
    final ConnectorBuilderProject project = builderProjectFromUpdate(projectUpdate);
    final Optional<ConnectorBuilderProject> storedProject =
        configRepository.getConnectorBuilderProject(project.getBuilderProjectId(), project.getWorkspaceId());

    if (storedProject.isEmpty()) {
      throw new IdNotFoundKnownException("Cannot find builder project with the given id for this workspace",
          projectUpdate.getBuilderProjectId().toString());
    }

    configRepository.writeBuilderProject(project);
  }

  public void deleteConnectorBuilderProject(final ConnectorBuilderProjectIdWithWorkspaceId projectDelete)
      throws IOException {
    final Optional<ConnectorBuilderProject> storedProject =
        configRepository.getConnectorBuilderProject(projectDelete.getBuilderProjectId(), projectDelete.getWorkspaceId());

    if (storedProject.isEmpty()) {
      throw new IdNotFoundKnownException("Cannot find builder project with the given id for this workspace",
          projectDelete.getBuilderProjectId().toString());
    }

    configRepository.deleteBuilderProject(projectDelete.getBuilderProjectId(), projectDelete.getWorkspaceId());
  }

}
